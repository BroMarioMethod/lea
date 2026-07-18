#!/usr/bin/env bash

set -u
set -o pipefail

readonly SCRIPT_NAME="$(basename "$0")"

created_count=0
skipped_count=0
error_count=0

print_usage() {
    cat <<EOF
Usage: ${SCRIPT_NAME} [REPOSITORY_ROOT]

Create or repair the LEA repository structure.

Arguments:
  REPOSITORY_ROOT  Repository to bootstrap.
                   Defaults to the current working directory.
EOF
}

report_ok() {
    printf '[ OK ] %s\n' "$1"
    created_count=$((created_count + 1))
}

report_skip() {
    printf '[SKIP] %s\n' "$1"
    skipped_count=$((skipped_count + 1))
}

report_error() {
    printf '[ERROR] %s\n' "$1" >&2
    error_count=$((error_count + 1))
}

normalise_root() {
    local requested_root="$1"

    if [[ ! -d "$requested_root" ]]; then
        printf 'Repository root does not exist: %s\n' "$requested_root" >&2
        return 1
    fi

    (
        cd "$requested_root" 2>/dev/null &&
        pwd -P
    )
}

read_toml_array() {
    local configuration_file="$1"
    local array_name="$2"

    awk -v target="$array_name" '
        BEGIN {
            reading = 0
        }

        $0 ~ "^[[:space:]]*" target "[[:space:]]*=[[:space:]]*\\[" {
            reading = 1
            next
        }

        reading && /^[[:space:]]*\]/ {
            exit
        }

        reading {
            line = $0

            sub(/[[:space:]]*#.*/, "", line)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
            sub(/,$/, "", line)
            gsub(/^"|"$/, "", line)

            if (line != "") {
                print line
            }
        }
    ' "$configuration_file"
}

is_safe_relative_path() {
    local path="$1"
    local component

    [[ -n "$path" ]] || return 1
    [[ "$path" != /* ]] || return 1

    IFS='/' read -r -a components <<< "$path"

    for component in "${components[@]}"; do
        [[ -n "$component" ]] || return 1
        [[ "$component" != "." ]] || return 1
        [[ "$component" != ".." ]] || return 1
    done

    return 0
}

validate_paths() {
    local category="$1"
    shift

    local path

    for path in "$@"; do
        if ! is_safe_relative_path "$path"; then
            report_error "${category}: unsafe path '${path}'"
        fi
    done
}

create_directory() {
    local repository_root="$1"
    local relative_path="$2"
    local absolute_path="${repository_root}/${relative_path}"

    if [[ -d "$absolute_path" ]]; then
        report_skip "${relative_path}/"
        return
    fi

    if [[ -e "$absolute_path" ]]; then
        report_error "${relative_path}/ exists but is not a directory"
        return
    fi

    if mkdir -p "$absolute_path"; then
        report_ok "${relative_path}/"
    else
        report_error "unable to create ${relative_path}/"
    fi
}

create_required_file() {
    local repository_root="$1"
    local relative_path="$2"
    local absolute_path="${repository_root}/${relative_path}"
    local parent_directory

    if [[ -f "$absolute_path" ]]; then
        report_skip "$relative_path"
        return
    fi

    if [[ -e "$absolute_path" ]]; then
        report_error "${relative_path} exists but is not a regular file"
        return
    fi

    parent_directory="$(dirname "$absolute_path")"

    if ! mkdir -p "$parent_directory"; then
        report_error "unable to create parent directory for ${relative_path}"
        return
    fi

    if : > "$absolute_path"; then
        report_ok "$relative_path"
    else
        report_error "unable to create ${relative_path}"
    fi
}

create_gitkeep() {
    local repository_root="$1"
    local relative_directory="$2"
    local absolute_directory="${repository_root}/${relative_directory}"
    local gitkeep_path="${absolute_directory}/.gitkeep"

    if [[ ! -d "$absolute_directory" ]]; then
        report_error "${relative_directory}/ is unavailable for .gitkeep"
        return
    fi

    if [[ -f "$gitkeep_path" ]]; then
        report_skip "${relative_directory}/.gitkeep"
        return
    fi

    if [[ -e "$gitkeep_path" ]]; then
        report_error "${relative_directory}/.gitkeep exists but is not a regular file"
        return
    fi

    if find "$absolute_directory" -mindepth 1 -maxdepth 1 -print -quit |
        grep -q .; then
        report_skip "${relative_directory}/.gitkeep"
        return
    fi

    if : > "$gitkeep_path"; then
        report_ok "${relative_directory}/.gitkeep"
    else
        report_error "unable to create ${relative_directory}/.gitkeep"
    fi
}

print_summary() {
    printf '\nBootstrap summary\n'
    printf '  Created: %d\n' "$created_count"
    printf '  Skipped: %d\n' "$skipped_count"
    printf '  Errors:  %d\n' "$error_count"
}

main() {
    local requested_root="${1:-.}"
    local repository_root
    local configuration_file

    local -a directories
    local -a required_files
    local -a tracked_empty_directories

    if [[ "$#" -gt 1 ]]; then
        print_usage >&2
        return 2
    fi

    if [[ "$requested_root" == "-h" || "$requested_root" == "--help" ]]; then
        print_usage
        return 0
    fi

    if ! repository_root="$(normalise_root "$requested_root")"; then
        return 2
    fi

    configuration_file="${repository_root}/config/repository_layout.toml"

    if [[ ! -f "$configuration_file" ]]; then
        printf 'Layout configuration not found: %s\n' \
            "$configuration_file" >&2
        return 2
    fi

    mapfile -t directories < <(
        read_toml_array "$configuration_file" "directories"
    )

    mapfile -t required_files < <(
        read_toml_array "$configuration_file" "required_files"
    )

    mapfile -t tracked_empty_directories < <(
        read_toml_array \
            "$configuration_file" \
            "tracked_empty_directories"
    )

    if [[ "${#directories[@]}" -eq 0 ]]; then
        report_error "configuration contains no required directories"
    fi

    validate_paths "directory" "${directories[@]}"
    validate_paths "required file" "${required_files[@]}"
    validate_paths \
        "tracked empty directory" \
        "${tracked_empty_directories[@]}"

    if [[ "$error_count" -gt 0 ]]; then
        print_summary
        return 1
    fi

    printf 'Bootstrapping repository: %s\n\n' "$repository_root"

    local path

    for path in "${directories[@]}"; do
        create_directory "$repository_root" "$path"
    done

    for path in "${required_files[@]}"; do
        create_required_file "$repository_root" "$path"
    done

    for path in "${tracked_empty_directories[@]}"; do
        create_gitkeep "$repository_root" "$path"
    done

    print_summary

    if [[ "$error_count" -gt 0 ]]; then
        return 1
    fi

    return 0
}

main "$@"
