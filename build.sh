
set -e
cd "$(dirname "$0")"

# tkinter must be installed on the build machine (Debian/Ubuntu: sudo apt install python3-tk)
python3 -c "import tkinter" 2>/dev/null || {
    echo "tkinter is missing. Install it first, e.g.:  sudo apt install python3-tk"
    exit 1
}

# the packages the app imports must be installed in the Python used for building
python3 -c "import numpy, scipy, matplotlib, tifffile, serial, PIL, fabio, pyedflib, h5py" 2>/dev/null || {
    echo "Missing packages. Install them with:"
    echo "  pip install numpy scipy matplotlib tifffile pyserial pillow fabio pyedflib h5py"
    exit 1
}

python3 -m PyInstaller --version >/dev/null 2>&1 || pip install pyinstaller

rm -rf build dist DarkfieldGUI.spec

python3 -m PyInstaller --noconfirm --onedir --name DarkfieldGUI \
    --paths . --paths gui \
    --hidden-import matplotlib.backends.backend_tkagg \
    --hidden-import mock_serial \
    gui/xrayGUI.py

# a double-clickable launcher entry; edit Exec to the folder you put the app in
cat > dist/DarkfieldGUI/DarkfieldGUI.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Darkfield Imaging
Exec=sh -c 'cd "$(dirname "$(readlink -f "%k")")" && ./DarkfieldGUI'
Terminal=false
EOF
chmod +x dist/DarkfieldGUI/DarkfieldGUI.desktop

# a tarball keeps the "executable" permission when copied to a FAT/exFAT USB stick
tar -czf dist/DarkfieldGUI.tar.gz -C dist DarkfieldGUI

echo
echo "Done."
echo "  Test it:        dist/DarkfieldGUI/DarkfieldGUI"
echo "  Copy to a USB:  dist/DarkfieldGUI.tar.gz   (extract it on the target, then run DarkfieldGUI)"