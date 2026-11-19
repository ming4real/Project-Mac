SUMMARY = "USB rescue and installation image for the MacBook Pro 14,3"
LICENSE = "MIT"

require mac-image-common.inc

IMAGE_INSTALL:append = " macbookpro-installer"
PACKAGE_FEED_URIS = ""
