#!/usr/bin/env bash

set -euo pipefail

readonly TASKWARRIOR_VERSION="3.4.2"
readonly TASKWARRIOR_PLATFORM="linux-aarch64"
readonly TASKWARRIOR_ARCHIVE="/opt/lea-release-assets/task-3.4.2.tar.gz"
readonly TASKWARRIOR_SHA256="d302761fcd1268e4a5a545613a2b68c61abd50c0bcaade3b3e68d728dd02e716"
readonly TASKWARRIOR_BUILD_DIRECTORY="/var/tmp/lea-taskwarrior-build"
readonly TASKWARRIOR_BUILD_CONCURRENCY="1"

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
        "src/lea"
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

main() {
    local repository_root
    local uv_binary

    repository_root="$(resolve_repository_root)"
    require_repository "$repository_root"

    if ! contains_help_request "$@"; then
        require_root
    fi

    uv_binary="$(resolve_uv)"

    cd -- "$repository_root"

    exec "$uv_binary" run lea install-release-candidate \
        --taskwarrior-source-archive "$TASKWARRIOR_ARCHIVE" \
        --taskwarrior-sha256 "$TASKWARRIOR_SHA256" \
        --taskwarrior-version "$TASKWARRIOR_VERSION" \
        --taskwarrior-platform "$TASKWARRIOR_PLATFORM" \
        --taskwarrior-build-directory "$TASKWARRIOR_BUILD_DIRECTORY" \
        --taskwarrior-build-concurrency "$TASKWARRIOR_BUILD_CONCURRENCY" \
        "$@"
}

main "$@"
