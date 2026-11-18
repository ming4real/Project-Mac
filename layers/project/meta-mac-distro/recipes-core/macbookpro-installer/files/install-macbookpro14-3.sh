#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -Eeuo pipefail
export LC_ALL=C

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

usage() {
    printf '%s\n' \
        "Usage: $0 [--dry-run] [--backup-dir DIR] <image.wic[.zst]> /dev/nvme0n1 [external-backup]" \
        'The installer preserves EFI/APPLE from the SSD automatically.' \
        'Use --backup-dir to choose a persistent destination for the new backup.' \
        'If the SSD has no Apple EFI files, supply an external directory containing APPLE.' \
        'A real installation erases the entire SSD.'
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    exit 0
fi

dry_run=false
backup_destination=
while (( $# )); do
    case "$1" in
        --dry-run) dry_run=true; shift ;;
        --backup-dir)
            [[ -n "${2:-}" ]] || die '--backup-dir requires a directory.'
            backup_destination=$2
            shift 2
            ;;
        --) shift; break ;;
        -*) die "Unknown option: $1" ;;
        *) break ;;
    esac
done
if (( $# < 2 || $# > 3 )); then
    usage >&2
    exit 2
fi
(( EUID == 0 )) || die 'Run as root from the rescue image.'
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

for cmd in awk blockdev cp df du find findmnt flock install losetup lsblk \
    mkdir mkfs.ext4 mkfs.fat mktemp mount readlink rm sfdisk stat swapon \
    sha256sum sort sync udevadm umount xargs zstd; do
    command -v "$cmd" >/dev/null || die "Missing required command: $cmd"
done

workdir=
mounts=()
efi_loop=
root_loop=
backup_dir=
backup_kind=
backup_verified=false
target_write_started=false
installed=false
stage='checking inputs'

cleanup() {
    local status=$1 i loop failed=0
    trap - EXIT
    trap '' INT TERM HUP
    for ((i=${#mounts[@]}-1; i>=0; i--)); do
        if findmnt --noheadings --mountpoint "${mounts[i]}" >/dev/null; then
            umount -- "${mounts[i]}" || failed=1
        fi
    done
    if (( ! failed )); then
        for loop in "$root_loop" "$efi_loop"; do
            [[ -z "$loop" ]] || losetup -d "$loop" || failed=1
        done
    fi
    if [[ -n "$workdir" ]]; then
        if (( ! failed )); then
            rm -rf --one-file-system -- "$workdir" || failed=1
        fi
        if (( failed )); then
            printf 'ERROR: Cleanup incomplete. Inspect %s before retrying.\n' "$workdir" >&2
        fi
    fi
    if (( status == 0 && failed )); then
        status=1
    fi
    if [[ -n "$backup_dir" ]]; then
        if [[ "$backup_verified" == false ]] ||
           { [[ "$backup_kind" == ram ]] &&
             { [[ "$target_write_started" == false ]] || { [[ "$installed" == true ]] && (( status == 0 )); }; }; }; then
            rm -rf --one-file-system -- "$backup_dir" || status=1
        else
            printf 'Apple EFI backup retained at %s\n' "$backup_dir" >&2
        fi
    fi
    if (( status == 0 )) && [[ "$installed" == true ]]; then
        printf 'Installed to %s. Root PARTUUID: %s\n' "$disk" "${root_uuid,,}"
    fi
    exit "$status"
}

trap 'cleanup "$?"' EXIT
trap 'printf "ERROR: Failed while %s (line %s, status %s).\n" "$stage" "$LINENO" "$?" >&2' ERR
trap 'die "Interrupted while $stage."' INT TERM HUP

case "$1" in
    *.wic|*.wic.zst) ;;
    *) die 'Expected a .wic or .wic.zst file.' ;;
esac
image=$(readlink -e -- "$1") || die "Cannot resolve image: $1"
[[ -f "$image" && -r "$image" ]] || die "Image is not a readable regular file: $image"
disk=$(readlink -e -- "$2") || die "Cannot resolve target disk: $2"
[[ "$disk" == /dev/nvme0n1 && -b "$disk" ]] || die 'Target must be /dev/nvme0n1.'
[[ "$(lsblk -dnro TYPE -- "$disk")" == disk ]] || die 'Target must be a whole disk.'
[[ "$(blockdev --getss "$disk")" == 4096 ]] || die 'Target must have 4096-byte logical sectors.'
[[ "$(blockdev --getro "$disk")" == 0 ]] || die 'Target is read-only.'
disk_id=$(lsblk -dnro MAJ:MIN -- "$disk")

check_backing_device() {
    local device=$1 path=$2 require_persistent=${3:-false} ancestry id type name
    ancestry=$(lsblk --inverse --raw --noheadings --output MAJ:MIN,TYPE,KNAME -- "$device") ||
        die "Cannot trace the backing device for $path"
    [[ -n "$ancestry" ]] || die "Cannot trace the backing device for $path"
    while read -r id type name; do
        [[ "$id" != "$disk_id" ]] || die "Path depends on target disk: $path"
        [[ "$type" != loop ]] || die "Loop-backed paths are unsupported: $path"
        [[ "$require_persistent" == false || ( "$name" != zram[0-9]* && "$name" != ram[0-9]* ) ]] ||
            die "Use a block device backed by persistent storage for $path."
    done <<< "$ancestry"
}

location_kind() {
    local path=$1 source device_id fstype
    source=$(findmnt --uniq --target "$path" --noheadings --nofsroot --output SOURCE) ||
        die "Cannot identify the filesystem containing $path"
    # The kernel can report /dev/root for the boot filesystem without a node
    # by that name in the rescue system's /dev.
    if [[ ! -b "$source" ]]; then
        device_id=$(findmnt --uniq --target "$path" --noheadings --output MAJ:MIN) ||
            die "Cannot find the device number for $path"
        source="/dev/block/$device_id"
    fi
    if [[ -b "$source" ]]; then
        check_backing_device "$source" "$path" true
        printf 'persistent\n'
        return
    fi
    fstype=$(findmnt --uniq --target "$path" --noheadings --output FSTYPE) ||
        die "Cannot identify the filesystem type for $path"
    if [[ "$fstype" == tmpfs || "$fstype" == ramfs ]]; then
        printf 'ram\n'
        return
    fi
    die "Use a filesystem on separate persistent media for $path (found $fstype)."
}

check_location() {
    local kind
    kind=$(location_kind "$1") || die "Unsafe or unsupported storage for $1"
    [[ "$2" != persistent || "$kind" == persistent ]] ||
        die "Use separate persistent storage for $1"
}

check_target_idle() {
    local devices id mountpoints swap swaps
    local -a holders
    [[ "$(lsblk -dnro MAJ:MIN -- "$disk")" == "$disk_id" ]] || die 'Target device changed.'
    devices=$(lsblk --raw --noheadings --output MAJ:MIN,MOUNTPOINTS -- "$disk")
    [[ -n "$devices" ]] || die 'Cannot enumerate target devices.'
    while read -r id mountpoints; do
        [[ -z "$mountpoints" ]] || die "Target device $id is mounted or in use as swap."
        [[ -d "/sys/dev/block/$id/holders" ]] || die "Cannot inspect target device $id."
        holders=(/sys/dev/block/"$id"/holders/*)
        [[ ! -e "${holders[0]}" ]] || die "Target device $id has active block-device holders."
    done <<< "$devices"

    swaps=$(swapon --show=NAME --noheadings --raw)
    while IFS= read -r swap; do
        [[ -n "$swap" ]] || continue
        printf -v swap '%b' "$swap"
        if [[ -b "$swap" ]]; then
            check_backing_device "$swap" "$swap"
        else
            check_location "$swap" temporary
        fi
    done <<< "$swaps"
}

check_sources() {
    check_location "$image" temporary
    check_location "$workdir" temporary
    [[ "$(location_kind "$apple")" == "$backup_kind" ]] || die 'Apple EFI backup storage changed.'
}

check_target_idle
check_location "$image" temporary

# Serialize discovery and installation, including compressed WIC staging.
check_location /run temporary
exec {lock_fd}>/run/install-macbookpro14-3.lock
flock --nonblock "$lock_fd" || die 'Another installer is running.'

scratch=$(readlink -e -- "${TMPDIR:-/tmp}") || die 'Cannot resolve TMPDIR.'
[[ -d "$scratch" ]] || die "Scratch path is not a directory: $scratch"
check_location "$scratch" temporary
workdir=$(mktemp -d -- "$scratch/mac-install.XXXXXX")
wic="$image"
if [[ "$1" == *.wic.zst ]]; then
    stage='decompressing image'
    wic="$workdir/image.wic"
    printf 'Decompressing %s in %s\n' "$image" "$workdir"
    zstd -d --sparse -o "$wic" -- "$image"
fi

stage='reading the WIC partition table'
sfdisk --verify "$wic" >/dev/null
# The shared WIC layout has a 512-byte-sector GPT and two partitions.
# Read offsets and sizes in sectors from the image, and convert to bytes below.
layout=$(sfdisk --dump "$wic" | awk '
    /^label: gpt$/       { gpt = 1 }
    /^sector-size: 512$/ { sectors = 1 }
    / : start=[[:blank:]]*[0-9]+,/ {
        sub(/^.* : start=[[:blank:]]*/, "")
        split($0, fields, /,[[:blank:]]*/)
        start = fields[1]
        size = fields[2]
        sub(/^size=[[:blank:]]*/, "", size)
        type = tolower(fields[3])
        sub(/^type=/, "", type)
        uuid = tolower(fields[4])
        sub(/^uuid=/, "", uuid)
        if (start !~ /^[0-9]+$/ || size !~ /^[0-9]+$/) exit 1
        if (++n == 1 && type == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
            efi = start " " size
        if (n == 2 && type == "0fc63daf-8483-4772-8e79-3d69d8477de4")
            root = start " " size " " uuid
    }
    END {
        if (!gpt || !sectors || n != 2 || efi == "" || root == "") exit 1
        print efi, root
    }
') || die 'Expected a 512-byte-sector GPT with an EFI and a Linux partition.'
read -r efi_start efi_sectors root_start root_sectors source_uuid <<< "$layout"
uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
[[ "$source_uuid" =~ $uuid_pattern ]] || die 'Invalid WIC root PARTUUID.'
image_bytes=$(stat -c %s -- "$wic")
(( efi_start > 0 && efi_sectors > 0 && root_sectors > 0 &&
   efi_start + efi_sectors <= root_start &&
   root_start + root_sectors <= image_bytes / 512 )) || die 'Invalid WIC partition bounds.'
efi_offset=$((efi_start * 512))
efi_bytes=$((efi_sectors * 512))
root_offset=$((root_start * 512))
root_bytes=$((root_sectors * 512))
disk_bytes=$(blockdev --getsize64 "$disk")
# Reserve the target ESP plus space for alignment and both GPT headers.
(( disk_bytes - 514 * 1024 * 1024 >= root_bytes )) || die 'Target SSD is too small for this WIC.'

printf 'WIC EFI:  offset %s, size %s bytes\n' "$efi_offset" "$efi_bytes"
printf 'WIC root: offset %s, size %s bytes\n' "$root_offset" "$root_bytes"
lsblk --output NAME,SIZE,MODEL,FSTYPE,MOUNTPOINTS -- "$disk"

apple_has_files() {
    local tree=$1 unexpected files
    [[ -d "$tree" && ! -L "$tree" ]] || die "Expected an APPLE directory at $tree"
    unexpected=$(find "$tree" ! -type d ! -type f -print -quit) || die "Cannot inspect $tree"
    [[ -z "$unexpected" ]] || die "Non-regular entry in Apple EFI tree: $unexpected"
    files=$(find "$tree" -type f -print -quit) || die "Cannot inspect $tree"
    [[ -n "$files" ]]
}

apple_fingerprint() (
    apple_has_files "$1" || die "No Apple EFI files in $1"
    cd -- "$1" || exit 1
    # Compare relative paths, directories and file contents. FAT metadata such
    # as timestamps and permissions can change across copies.
    {
        find . -type d -print0 | sort -z || exit 1
        find . -type f -print0 | sort -z | xargs -0 -r sha256sum --zero --
    } | sha256sum
)

verify_apple() {
    local actual
    actual=$(apple_fingerprint "$1") || die "Cannot verify Apple EFI files at $1"
    [[ "$actual" == "$apple_expected" ]] || die "Apple EFI tree differs from the verified source at $1"
}

backup_destination_eligible() {
    local dir=$1 options available
    [[ -d "$dir" && -w "$dir" && -x "$dir" ]] || return 1
    options=$(findmnt --uniq --target "$dir" --noheadings --output VFS-OPTIONS) || return 1
    [[ ",$options," == *,rw,* ]] || return 1
    available=$(df -B1 --output=avail -- "$dir" | awk 'NR == 2 { print $1 }') || return 1
    [[ "$available" =~ ^[0-9]+$ ]] && (( available >= apple_bytes + 1024 * 1024 ))
}

choose_backup_destination() {
    local candidate dir kind targets
    local -a candidates=("${image%/*}/" "$scratch" /var/lib /run)
    if [[ -n "$backup_destination" ]]; then
        backup_parent=$(readlink -e -- "$backup_destination") || die 'Cannot resolve --backup-dir.'
        check_location "$backup_parent" persistent
        backup_destination_eligible "$backup_parent" || die "Cannot store the backup in $backup_parent"
        backup_kind=persistent
        return
    fi

    targets=$(findmnt --raw --noheadings --output TARGET)
    while IFS= read -r candidate; do
        printf -v candidate '%b' "$candidate"
        case "$candidate" in
            /mnt/*|/media/*|/run/media/*) candidates+=("$candidate") ;;
        esac
    done <<< "$targets"

    for candidate in "${candidates[@]}"; do
        dir=$(readlink -e -- "$candidate") || continue
        kind=$(location_kind "$dir" 2>/dev/null) || continue
        backup_destination_eligible "$dir" || continue
        # Keep the first usable RAM location while looking for persistent storage.
        if [[ "$kind" == persistent || -z "$backup_parent" ]]; then
            backup_parent=$dir
            backup_kind=$kind
        fi
        [[ "$kind" != persistent ]] || return 0
    done
    [[ -n "$backup_parent" ]] || die 'No eligible backup location. Mount separate storage and use --backup-dir.'
}

stage='discovering Apple EFI files on the SSD'
check_target_idle
old_efi="$workdir/old-efi"
mkdir -- "$old_efi"
mounts+=("$old_efi")
esp_type='c12a7328-f81f-11d2-ba4b-00a0c93ec93b'
devices=$(lsblk --raw --noheadings --output PATH,TYPE,PARTTYPE -- "$disk")
apple_part=
while read -r part type parttype; do
    [[ "$type" == part ]] || continue
    [[ -n "$parttype" ]] || die "Cannot determine the partition type of $part"
    [[ "${parttype,,}" == "$esp_type" || "${parttype,,}" == 0xef ]] || continue
    mount -t vfat -o ro,nosuid,nodev,noexec -- "$part" "$old_efi" ||
        die "Cannot inspect EFI partition $part read-only. Resolve the mount failure before installing."
    tree="$old_efi/EFI/APPLE"
    if [[ -e "$tree" || -L "$tree" ]] && apple_has_files "$tree"; then
        [[ -z "$apple_part" ]] || die 'Multiple EFI partitions contain Apple files. Resolve which ESP to preserve before installing.'
        apple_part=$part
        apple_expected=$(apple_fingerprint "$tree")
        usage_bytes=$(du -s -B1 -- "$tree")
        read -r apple_bytes _ <<< "$usage_bytes"
    fi
    umount -- "$old_efi"
done <<< "$devices"

stage='checking Apple EFI backup eligibility'
if [[ -n "$apple_part" ]]; then
    backup_parent=
    choose_backup_destination
    printf 'Found Apple EFI files on %s. Backup destination: %s (%s).\n' "$apple_part" "$backup_parent" "$backup_kind"
    if [[ "$backup_kind" == ram ]]; then
        printf '%s\n' 'A RAM-only backup will be lost on power failure or reboot. A real install requires explicit RAM backup confirmation.' >&2
    fi
else
    [[ -n "${3:-}" ]] || die 'No Apple EFI files found on the SSD. Supply an external backup directory containing APPLE.'
    external_backup=$(readlink -e -- "$3") || die "Cannot resolve external backup: $3"
    apple="$external_backup/APPLE"
    backup_kind=persistent
    check_location "$apple" persistent
    apple_expected=$(apple_fingerprint "$apple")
    printf 'Using verified external Apple EFI backup: %s\n' "$apple"
fi

if [[ "$dry_run" == true ]]; then
    printf '%s\n' 'Dry-run passed. Checked the WIC GPT, SSD eligibility and Apple EFI backup plan.'
    exit 0
fi

stage='mounting WIC partitions read-only'
source_efi="$workdir/source-efi"
source_root="$workdir/source-root"
target_efi="$workdir/target-efi"
target_root="$workdir/target-root"
mkdir -- "$source_efi" "$source_root" "$target_efi" "$target_root"
mounts+=("$source_efi" "$source_root" "$target_root" "$target_efi")

efi_loop=$(losetup --find --show --read-only --offset "$efi_offset" --sizelimit "$efi_bytes" -- "$wic")
root_loop=$(losetup --find --show --read-only --offset "$root_offset" --sizelimit "$root_bytes" -- "$wic")
mount -t vfat -o ro -- "$efi_loop" "$source_efi"
mount -t ext4 -o ro,noload -- "$root_loop" "$source_root"

stage='validating WIC boot files'
grub="$source_efi/EFI/BOOT/grub.cfg"
fstab="$source_root/etc/fstab"
[[ -s "$source_efi/EFI/BOOT/bootx64.efi" && -s "$source_efi/bzImage" && -s "$grub" ]] ||
    die 'WIC EFI partition is missing the bootloader, GRUB config or kernel.'
[[ ! -e "$source_efi/EFI/APPLE" ]] || die 'Unexpected APPLE directory in the source WIC.'
[[ -L "$source_root/sbin/init" || -x "$source_root/sbin/init" ]] ||
    die 'WIC root partition is missing /sbin/init.'
[[ -f "$fstab" && ! -L "$fstab" ]] || die 'WIC root partition is missing /etc/fstab.'

write_grub_config() {
    awk -v old="$source_uuid" -v new="$1" '
        $1 == "linux" || $1 == "linuxefi" {
            roots = 0
            for (i = 2; i <= NF; i++) {
                if ($i ~ /^root=/) roots++
                if (tolower($i) == "root=partuuid=" old) {
                    $i = "root=PARTUUID=" new
                    updated++
                    matched = 1
                }
            }
            if (roots != 1 || !matched) bad = 1
            matched = 0
        }
        { print }
        END { if (bad || !updated) exit 1 }
    ' "$grub"
}

write_grub_config "$source_uuid" >/dev/null || die 'GRUB root argument does not match the WIC GPT.'

if [[ -n "$apple_part" ]]; then
    stage='preserving Apple EFI files from the SSD'
    check_target_idle
    [[ "$(location_kind "$backup_parent")" == "$backup_kind" ]] || die 'Backup destination storage changed.'
    backup_destination_eligible "$backup_parent" || die "Cannot store the backup in $backup_parent"
    mount -t vfat -o ro,nosuid,nodev,noexec -- "$apple_part" "$old_efi"
    backup_dir=$(mktemp -d -- "$backup_parent/mac-apple-efi.XXXXXX")
    apple="$backup_dir/APPLE"
    cp -R -- "$old_efi/EFI/APPLE" "$apple"
    sync -f -- "$backup_dir"
    verify_apple "$apple"
    backup_verified=true
    umount -- "$old_efi"
    printf 'Verified Apple EFI backup at %s\n' "$backup_dir"
    if [[ "$backup_kind" == ram ]]; then
        printf '%s\n' 'The only verified backup outside the SSD is in RAM. Power loss or reboot during installation can permanently lose the Apple EFI files.' >&2
        read -r -p 'Type RAM BACKUP to accept that risk: ' confirm || die 'Installation cancelled.'
        [[ "$confirm" == 'RAM BACKUP' ]] || die 'Installation cancelled.'
    fi
fi

printf '\nALL DATA ON %s WILL BE ERASED.\n' "$disk" >&2
read -r -p 'Type ERASE to continue: ' confirm || die 'Installation cancelled.'
[[ "$confirm" == ERASE ]] || die 'Installation cancelled.'
stage='rechecking target and sources before writing'
check_target_idle
check_sources
verify_apple "$apple"

stage='creating a native 4Kn GPT'
printf 'Creating GPT on %s\n' "$disk"
target_write_started=true
sfdisk --lock=nonblock --wipe always --wipe-partitions always "$disk" <<'PARTITIONS'
label: gpt
unit: sectors
sector-size: 4096

size=512MiB, type=uefi, name="EFI"
type=linux, name="platform"
PARTITIONS
udevadm settle
efi_part="${disk}p1"
root_part="${disk}p2"
[[ -b "$efi_part" && -b "$root_part" ]] || die 'New GPT partitions did not appear.'
check_target_idle

efi_uuid=$(sfdisk --part-uuid "$disk" 1)
root_uuid=$(sfdisk --part-uuid "$disk" 2)
[[ "$efi_uuid" =~ $uuid_pattern && "$root_uuid" =~ $uuid_pattern ]] ||
    die 'Cannot read new partition UUIDs.'

stage='formatting target filesystems'
mkfs.fat -F 32 -S 4096 -s 1 -n EFI "$efi_part"
mkfs.ext4 -L platform "$root_part"

stage='mounting and populating the target filesystems'
mount -t ext4 -- "$root_part" "$target_root"
mount -t vfat -- "$efi_part" "$target_efi"

cp -a -- "$source_root/." "$target_root/"
cp -R -- "$source_efi/." "$target_efi/"

stage='restoring and verifying Apple EFI files'
restored="$target_efi/EFI/APPLE"
[[ ! -e "$restored" && ! -L "$restored" ]] || die 'Unexpected APPLE directory in the WIC EFI files.'
cp -R -- "$apple" "$restored"
sync -f -- "$target_efi"
verify_apple "$restored"

stage='configuring the installed boot files'
write_grub_config "${root_uuid,,}" > "$target_efi/EFI/BOOT/grub.cfg"
# WIC may add a /dev/sda1 /boot entry to the BSP fstab. The new disk's
# ESP must be selected even when the rescue USB is still attached.
awk -v uuid="${efi_uuid,,}" '
    /^[[:blank:]]*#/ || $2 != "/boot" { print }
    END { printf "PARTUUID=%s\t/boot\tvfat\tdefaults\t0\t0\n", uuid }
' "$fstab" > "$workdir/fstab"
install -m 0644 -- "$workdir/fstab" "$target_root/etc/fstab"

stage='flushing and unmounting the installed filesystems'
sync -f -- "$target_efi" "$target_root"
installed=true
