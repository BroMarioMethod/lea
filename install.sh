#!/usr/bin/env bash

set -euo pipefail

readonly TASKWARRIOR_VERSION="3.4.2"
readonly TASKWARRIOR_PLATFORM="linux-aarch64"
readonly TASKWARRIOR_ARCHIVE="/opt/lea-release-assets/task-3.4.2.tar.gz"
readonly TASKWARRIOR_SHA256="d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716"
readonly TASKWARRIOR_BUILD_DIRECTORY="/var/tmp/lea-taskwarrior-build"
readonly TASKWARRIOR_BUILD_CONCURRENCY="1"

readonly CALENDAR_REQUIREMENTS_RELATIVE_PATH="third_party/calendar/requirements-linux-aarch64-py313.txt"
readonly CALENDAR_REQUIREMENTS_SHA256="f5f7a0749b993e49bbd50b8807242611fff1dbc2477a59a4a292c0aa42420ba5"
readonly CALENDAR_PACKAGE_INDEX_URL="https://pypi.org/simple"
readonly CALENDAR_TOOLCHAIN_VERSION="1.0.0"
readonly CALENDAR_PLATFORM="linux-aarch64"
readonly CALENDAR_KHAL_VERSION="0.11.4"
readonly CALENDAR_VDIRSYNCER_VERSION="0.19.3"

resolve_repository_root() {
    local source="${BASH_SOURCE[0]}"
    local directory

    while [[ -L "$source" ]]; do
        directory="$(cd -P -- "$(dirname -- "$source")" && pwd)"
        source="$(readlink -- "$source")"
        if [[ "$source" != /* ]]; then
            source="${directory}/${source}"
        fi
    done

    cd -P -- "$(dirname -- "$source")" && pwd
}

contains_help_request() {
    local argument

    for argument in "$@"; do
        case "$argument" in
            -h|--help)
                return 0
                ;;
        esac
    done

    return 1
}

require_repository() {
    local repository_root="$1"
    local required_path

    for required_path in \
        "pyproject.toml" \
        "uv.lock" \
        "src/lea" \
        "third_party/calendar/requirements.in" \
        "third_party/calendar/requirements-linux-aarch64-py313.txt" \
        "third_party/calendar/SHA256SUMS"
    do
        if [[ ! -e "${repository_root}/${required_path}" ]]; then
            printf \
                'LEA repository is incomplete; missing: %s\n' \
                "${repository_root}/${required_path}" \
                >&2
            return 1
        fi
    done
}

require_root() {
    local user_id

    if ! user_id="$(id -u 2>/dev/null)"; then
        printf 'Unable to determine the current user ID.\n' >&2
        return 1
    fi

    if [[ "$user_id" != "0" ]]; then
        printf \
            'LEA installation must be run as root. Use: sudo ./install.sh\n' \
            >&2
        return 1
    fi
}

resolve_uv() {
    local candidate
    local sudo_home=""

    if [[ -n "${LEA_UV_BIN:-}" ]]; then
        if [[ "$LEA_UV_BIN" != /* ]]; then
            printf 'LEA_UV_BIN must be an absolute path.\n' >&2
            return 1
        fi
        if [[ ! -x "$LEA_UV_BIN" ]]; then
            printf 'LEA_UV_BIN is not executable: %s\n' "$LEA_UV_BIN" >&2
            return 1
        fi
        printf '%s\n' "$LEA_UV_BIN"
        return 0
    fi

    if candidate="$(command -v uv 2>/dev/null)" && [[ -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        if command -v getent >/dev/null 2>&1; then
            sudo_home="$(
                getent passwd "$SUDO_USER" \
                    | awk -F: 'NR == 1 { print $6 }'
            )"
        fi

        if [[ -z "$sudo_home" ]]; then
            sudo_home="/home/${SUDO_USER}"
        fi

        candidate="${sudo_home}/.local/bin/uv"
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    for candidate in \
        "/usr/local/bin/uv" \
        "/usr/bin/uv" \
        "/root/.local/bin/uv"
    do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    printf \
        'Unable to locate uv. Install uv or set LEA_UV_BIN to its absolute path.\n' \
        >&2
    return 1
}

resolve_calendar_python() {
    local candidate

    if [[ -n "${LEA_CALENDAR_PYTHON_BIN:-}" ]]; then
        if [[ "$LEA_CALENDAR_PYTHON_BIN" != /* ]]; then
            printf 'LEA_CALENDAR_PYTHON_BIN must be an absolute path.\n' >&2
            return 1
        fi

        if [[ ! -x "$LEA_CALENDAR_PYTHON_BIN" ]]; then
            printf \
                'LEA_CALENDAR_PYTHON_BIN is not executable: %s\n' \
                "$LEA_CALENDAR_PYTHON_BIN" \
                >&2
            return 1
        fi

        printf '%s\n' "$LEA_CALENDAR_PYTHON_BIN"
        return 0
    fi

    for candidate in \
        "/usr/bin/python3.13" \
        "/usr/local/bin/python3.13"
    do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    if candidate="$(command -v python3.13 2>/dev/null)" \
        && [[ -x "$candidate" ]]
    then
        printf '%s\n' "$candidate"
        return 0
    fi

    printf \
        'Unable to locate Python 3.13. Set LEA_CALENDAR_PYTHON_BIN to its absolute path.\n' \
        >&2
    return 1
}

main() {
    local repository_root
    local uv_binary
    local calendar_python
    local calendar_requirements_lock

    repository_root="$(resolve_repository_root)"
    require_repository "$repository_root"

    if ! contains_help_request "$@"; then
        require_root
    fi

    uv_binary="$(resolve_uv)"
    calendar_python="$(resolve_calendar_python)"
    calendar_requirements_lock="${repository_root}/${CALENDAR_REQUIREMENTS_RELATIVE_PATH}"

    cd -- "$repository_root"

    exec "$uv_binary" run lea install-release-candidate \
        --taskwarrior-source-archive "$TASKWARRIOR_ARCHIVE" \
        --taskwarrior-sha256 "$TASKWARRIOR_SHA256" \
        --taskwarrior-version "$TASKWARRIOR_VERSION" \
        --taskwarrior-platform "$TASKWARRIOR_PLATFORM" \
        --taskwarrior-build-directory "$TASKWARRIOR_BUILD_DIRECTORY" \
        --taskwarrior-build-concurrency "$TASKWARRIOR_BUILD_CONCURRENCY" \
        --calendar-requirements-lock "$calendar_requirements_lock" \
        --calendar-requirements-sha256 "$CALENDAR_REQUIREMENTS_SHA256" \
        --calendar-uv-executable "$uv_binary" \
        --calendar-python-executable "$calendar_python" \
        --calendar-package-index-url "$CALENDAR_PACKAGE_INDEX_URL" \
        --calendar-toolchain-version "$CALENDAR_TOOLCHAIN_VERSION" \
        --calendar-platform "$CALENDAR_PLATFORM" \
        --calendar-khal-version "$CALENDAR_KHAL_VERSION" \
        --calendar-vdirsyncer-version "$CALENDAR_VDIRSYNCER_VERSION" \
        "$@"
}

main "$@"
