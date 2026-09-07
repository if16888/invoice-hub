"""Generated build identity for frozen application packages.

The release workflow replaces this default before PyInstaller runs. Keeping the
module in the package gives frozen builds a version even when the user's
runtime environment has no CI variables.
"""

BUILD_VERSION = ""
