#!/bin/bash
echo
echo "*****************************************************************"
echo "* This script is for adding a new Hitachi Volume to this system *"
echo "*****************************************************************"
echo
neededPackagesInstalled=true
neededPackages=("multipath-tools" "dlm-controld" "gfs2-utils")
missingPackages=()
echo "Verifying needed packages are installed..."
for package in ${neededPackages[@]}; do
    if dpkg -s "$package" &>/dev/null; then
        echo -e "\tINSTALLED: $package"
    else
        echo -e "\tMISSING: $package"
        missingPackages+=("$package")
        neededPackagesInstalled=false
    fi
done
echo

if [[ "$neededPackagesInstalled" != true ]]; then
    echo "Not all needed packages are installed!"
    read -p "Install them now? (Y/N): " installPackagesNow
    if [[ "$installPackagesNow" == "Y" || "$installPackagesNow" == "y" ]]; then
        echo "Updating package list..."
        apt update
        echo Installing packages...
        for package in ${missingPackages[@]}; do
            echo -e "\tInstalling '$package'"
            apt-get install $package 1>/dev/null
        done
    fi
fi

volumeFound=false
while [[ "$volumeFound" != true ]]; do
    echo "Printing current volumes on the system"
    lsblk
    echo
    read -p "Is the new volume present in the list? (Y/N): " volumeFoundString

    if [[ "$volumeFound" != "Y" || "$volumeFound" != "y" ]]; then
        echo "Rescanning for volumes..."
    else
done
