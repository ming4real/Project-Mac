SUMMARY = "Yocto build-host tools for the Mac Linux workstation"
DESCRIPTION = "GNU C and C++ toolchain, host utilities, and Python and Perl tools for building OpenEmbedded images on Mac Linux."
LICENSE = "MIT"

PACKAGE_ARCH = "${TUNE_PKGARCH}"
PACKAGEGROUP_DISABLE_COMPLEMENTARY = "1"

inherit packagegroup

# Use OE package identifiers here. The package backend emits libc6-dev,
# libc6-utils, libgcc-s-dev, libcrypt-dev, and libacl1 on this distro.
RDEPENDS:${PN} = " \
    binutils \
    gcc gcc-symlinks \
    g++ g++-symlinks \
    cpp cpp-symlinks \
    make \
    glibc-dev glibc-utils ldd linux-libc-headers-dev \
    libgcc-dev libstdc++-dev libatomic-dev \
    libxcrypt-dev libgomp-dev libacl \
    autoconf automake m4 libtool pkgconf texinfo \
    bash coreutils diffutils findutils gawk grep sed \
    patch file chrpath cpio diffstat which \
    util-linux-flock util-linux-getopt util-linux-script \
    bzip2 gzip tar unzip xz zstd \
    ca-certificates git wget openssh-ssh openssh-scp \
    socat iproute2-ip iputils-ping procps-ps \
    rpcsvc-proto \
    perl perl-modules \
    python3-core python3-modules python3-venv \
    python3-git python3-jinja2 python3-pexpect \
    python3-pip python3-packaging python3-setuptools \
    python3-subunit python3-websockets \
    locale-base-en-us \
"