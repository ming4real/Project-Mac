require recipes-core/images/core-image-minimal.bb

IMAGE_FEATURES += "ssh-server-openssh package-management"

IMAGE_INSTALL:append = " \
    kernel-modules \
    linux-firmware \
    mac-debug-user \
    sudo \
    systemd-conf \
    systemd-networkd \
    vim \
"
