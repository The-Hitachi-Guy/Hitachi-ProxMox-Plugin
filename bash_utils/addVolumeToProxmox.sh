#!/bin/bash
get_disk_usage() {
    answer=
    validAnswer=false
    correct=false
    usageType=""
    while : ; do
        while [[ "$validAnswer" != true ]]; do
            echo "Disk Usage Types:" >&2
            echo "*****************" >&2
            echo "1) Proxmox Datastore" >&2
            echo "2) Raw Device Mapped (RDM) Volume" >&2
            echo >&2
            read -p "Choose disk usage type for disk $1: " answer
            if [[ "$answer" =~ ^[1-2]+$ ]]; then
                validAnswer=true
            else
                echo "Invalid response! Enter either 1 or 2." >&2
                echo >&2
            fi
        done


        if [[ "$answer" == "1" ]]; then
            usageType="datastore"
        else
            usageType="rdm"
        fi
        echo "You selected '$usageType' for disk $1." >&2
        read -p "Correct? (Y/N): " correct
        if [[ "$correct" == "Y" || "$correct" == "y" ]]; then
            echo "$usageType"
            break
        else
            validAnswer=false
        fi
        echo >&2
    done
}

######################################################
# Creates a single GPT partition on the specified disk
# Arguments:
#   $1 - Disk device (e.g., /dev/sdb)
# Returns:
#   None
######################################################
make_gpt_partition() {
    local disk=$1
    
    # Create a single GPT partition on the disk
    parted -s "$disk" mklabel gpt mkpart primary "1 -1"
    # Inform the OS of partition table changes
    kpartx -a "$disk-part1"
}

######################################################
# Rescan for new disks and multipath devices
# Returns:
#   None
######################################################
rescan_disks() {
    rescan=/usr/bin/rescan-scsi-bus.sh
    echo "Rescanning SCSI bus for new disks and multipath devices..."
    # Create a single GPT partition on the disk
    $rescan --multipath --largelun --color
}

#######################################################
# Handle multipath devices and get user to select disks
# Returns:
#  None
#######################################################
configure_multipath_for_disk() {
    ready="n"
    aliasCorrect="n"
    aliasName=""
    multipathFile="/etc/multipath.conf"
    multipathFile="./multipath.conf"
    multipathEntry=("\tmultipath {")
    
    echo "Configuring multipath for new disk $1..." 
    uuid=$(/usr/lib/udev/scsi_id --whitelisted --replace-whitespace --device= "$1")
    while [[ "$aliasCorrect" != "Y" && "$aliasCorrect" != "y" ]]; do
        read -p "Enter alias for new multipath device (e.g., mpatha): " aliasName
        read -p "Is '$aliasName' correct? (Y/N): " aliasCorrect
    done

    read -p "Ready to configure multipath device? (Y/N): " ready
    
    if [[ "$ready" != "Y" && "$ready" != "y" ]]; then
        multipathEntry+=($'\t\twwid'" $uuid")
        multipathEntry+=($'\t\talias'" $aliasName")
        multipathEntry+=($'\t}')
        echo "Adding multipath entry for disk $1 with UUID $uuid..."
        multipath -a $uuid
        echo "Creating multipath configuration for disk $1 with alias '$aliasName'..."
        for line in "${multipathEntry[@]}"; do
            sed -i "/# End of multipath devices/i\ $line {" $multipathFile
        done
        
        # Restart multipath service to apply changes
        # echo "Restarting multipath service..."
        # systemctl restart multipathd.service
    else
        echo "Skipping multipath configuration for disk $1."
    fi
    
}

rescan=/usr/bin/rescan-scsi-bus.sh
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

# DECLARE -A selectedDisks
# while [[ ${#selectedDisks} -lt 1 ]]; do
#     echo "Printing current volumes on the system"
#     /usr/bin/lsblk -o NAME,SIZE,MODEL,WWN
#     echo
#     read -p "Is the new volume present in the disk list? (Y/N): " volumeFound

#     if [[ "$volumeFound" != "Y" && "$volumeFound" != "y" ]]; then
#         read -p "Is this the first volume attached from this array? (Y/N): " firstVolume
#         if [[ "$firstVolume" == "Y" || "$firstVolume" == "y" ]]; then
#             echo "Performing LIP RESET and then rescanning ALL SCSI Targets..."
#             $rescan --issue-lip-wait=10 --multipath --largelun --color --alltargets
#         else
#             echo "Performing LIP RESET and then rescanning existing targets..."
#             $rescan --issue-lip-wait=10 --multipath --largelun --color
#         fi
#         echo
#     else
#         echo
#         read -p "Enter single SD Device name for each multipath volume (sda/sdb/sdc... space seperated): " -a selectedDisksStrings

#         actualDisks=($(ls /dev/sd? 2>/dev/null))
#         for disk in ${selectedDisksStrings[@]}; do
#             disk=/dev/$disk

#         echo
#     fi
# done
# diskTypeUsages=()
# for disk in ${selectedDisks[@]}; do
#     diskTypeUsages+=("$(get_disk_usage $disk)")
# done

# echo -e "Disk\tDiskTypeUsage"
# echo "********************"
# for i in "${!selectedDisks[@]}"; do
#     echo -e "${selectedDisks[$i]}\t${diskTypeUsages[$i]}"
# done


# printDisksAndDiskUsageTypes "${selectedDisks[@]}" "${diskTypeUsages[@]}"

echo "********************************"
echo "* New Disk(s) Selection Screen *"
echo "********************************"

valid_disks=()
valid_disks_correct="n"
rescan_disks
while [[ "$valid_disks_correct" != "Y" && "$valid_disks_correct" != "y" ]]; do
    # Get top-level sd devices with name, size, and WWN
    mapfile -t disks < <(lsblk -ndo NAME,SIZE,WWN,MODEL | grep 'OPEN-V')

    # Exit if no sd disks found
    if [[ ${#disks[@]} -eq 0 ]]; then
        echo "No /dev/sdX devices found."
        exit 1
    fi

    echo "Available Disks:"
    echo "----------------"
    for i in "${!disks[@]}"; do
        disk_name=$(awk '{print $1}' <<< "${disks[$i]}")
        disk_size=$(awk '{print $2}' <<< "${disks[$i]}")
        disk_wwn=$(awk '{print $3}' <<< "${disks[$i]}")
        disk_model=$(awk '{print $4}' <<< "${disks[$i]}")
        printf "%2d) /dev/%-5s Size: %-4s WWN: %-36s Model: %-14s\n" "$((i+1))" "$disk_name" "$disk_size" "${disk_wwn:-N/A}" "${disk_model}"
    done
    unset selections
    read -rp "Select one or more disks (space-separated numbers): " -a selections

    # Check that at least one selection was made
    if [[ ${#selections[@]} -eq 0 ]]; then
        echo "No selections made. Exiting."
        exit 1
    fi

    # Verify selections are valid and unique
    unset seen
    unset valid_disks
    declare -A seen
    valid_disks=()

    for sel in "${selections[@]}"; do
        # Ensure selection is a number and within range
        if [[ "$sel" =~ ^[0-9]+$ ]] && (( sel >= 1 && sel <= ${#disks[@]} )); then
            if [[ -n "${seen[$sel]}" ]]; then
                echo "Duplicate selection detected: $sel"
            else
                seen[$sel]=1
                valid_disks+=("/dev/$(awk '{print $1}' <<< "${disks[$((sel-1))]}")")
            fi
        else
            echo "Invalid selection: $sel"
        fi
    done

    # Print verified disks
    if [[ ${#valid_disks[@]} -gt 0 ]]; then
        echo
        echo "You selected the following valid disks:"
        printf ' - %s\n' "${valid_disks[@]}"
    else
        echo "No valid disks selected."
        exit 1
    fi

    read -p "Is this correct? (Y/N): " valid_disks_correct
    echo
done

for disk in ${valid_disks[@]}; do
    disk_usage=$(get_disk_usage "$disk")
    echo "Selected usage: $disk_usage"
    echo "$disk"

    if [[ "$disk_usage" == "datastore" ]]; then
        echo "Creating GPT partition on $disk..."
        make_gpt_partition "$disk"
        echo "Partition created."
    fi
done