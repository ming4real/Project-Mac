SUMMARY = "Local debugging account with public-key SSH access for the Mac images"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COREBASE}/meta/COPYING.MIT;md5=3da9cfbcb788c80a0384361b4de20420"

S = "${UNPACKDIR}"

inherit useradd

USERADD_PACKAGES = "${PN}"
MAC_USERNAME ?= "ming"
MAC_USER_HOME = "/home/${MAC_USERNAME}"
MAC_SSH_PUBLIC_KEY_STAGED ?= ""
# Keep the account package free of the initial password hash. The image sets
# the password after package installation.
USERADD_PARAM:${PN} = "--create-home --key HOME_MODE=0750 --home-dir ${MAC_USER_HOME} --shell /bin/sh --user-group --password '*NP*' ${MAC_USERNAME}"

# Rebuild this recipe's account database when the configured user changes so
# a previous user's sysroot entry cannot affect ownership or UID allocation.
do_prepare_recipe_sysroot[vardeps] += "USERADD_PARAM:${PN}"
do_prepare_recipe_sysroot[cleandirs] += "${RECIPE_SYSROOT} ${RECIPE_SYSROOT_NATIVE}"

# Include the staged file in the install signature as well as the staging path.
do_install[file-checksums] += "${@d.getVar('MAC_SSH_PUBLIC_KEY_STAGED') + ':True' if d.getVar('MAC_SSH_PUBLIC_KEY_STAGED') else ''}"

do_install() {
    if [ -z "${MAC_SSH_PUBLIC_KEY_STAGED}" ] || [ ! -r "${MAC_SSH_PUBLIC_KEY_STAGED}" ]; then
        bbfatal "Missing staged SSH public key. Set MAC_SSH_PUBLIC_KEY_FILE in .env and run scripts/yocto.py build."
    fi
    install -d -m 0750 "${D}${MAC_USER_HOME}"
    install -d -m 0700 "${D}${MAC_USER_HOME}/.ssh"
    install -m 0600 "${MAC_SSH_PUBLIC_KEY_STAGED}" "${D}${MAC_USER_HOME}/.ssh/authorized_keys"
    chown -R "${MAC_USERNAME}:${MAC_USERNAME}" "${D}${MAC_USER_HOME}"

    install -d -m 0750 "${D}${sysconfdir}/sudoers.d"
    printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "${MAC_USERNAME}" > "${D}${sysconfdir}/sudoers.d/90-mac-user"
    chmod 0440 "${D}${sysconfdir}/sudoers.d/90-mac-user"
}


FILES:${PN} = "${MAC_USER_HOME} ${sysconfdir}/sudoers.d/90-mac-user"
