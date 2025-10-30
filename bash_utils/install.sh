#!/bin/bash

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

list_disks() {
    # List discovered volume(s) and ask if reboot is needed
    echo "#######################################"
    echo "# Listing current disks of the system #"
    echo "#######################################"
    lsblk -o NAME,MODEL,SIZE,WWN
    echo
}

verify_disks_found() {
    disksVerified="N"
    while [[ "$disksVerified" != "Y" && "$disksVerified" != "y" ]]; do
        list_disks
        read -p "Are SAN volume(s) found? (Y/N): " foundVolumes
        if [ "$foundVolumes" == "Y" ] || [ "$foundVolumes" == "y" ]; then
            disksVerified="Y"
        else
            read -p "Do you want to rescan SCSI bus to find volumes? (Y/N): " rescanDisks
            if [ "$rescanDisks" == "Y" ] || [ "$rescanDisks" == "y" ]; then
                rescan-disks
            else
                read -p "Do you want to reboot this system to find volumes? (Y/N): " confirmReboot
                if [ "$confirmReboot" == "Y" ] || [ "$confirmReboot" == "y" ]; then
                    reboot
                else
                    echo "Exiting install now..."
                    exit 1
                fi
            fi
        fi
    done
    return 1
}

rescan-disks() {
    # Rescan SCSI Bus to detect the new volume(s)
    echo "#########################################"
    echo "# Rescanning SCSI Bus to find new disks #"
    echo "#########################################"
    rescan-scsi-bus.sh --largelun --multipath --issue-lip-wait=10 --alltargets
    echo
}

currentNodeName=$(hostname)
isClusterNode="N"
echo "Conifugure this system a standalone server or as a cluster node?"
echo "1) Standalone Server"
echo "2) Cluster Node (needs to be in the cluster already)"
read -p "Enter choice (1 or 2): " serverTypeChoice
if [ "$serverTypeChoice" == "1" ]; then
    echo "Will configure storage for Standalone Server..."
    isClusterNode="N"
elif [ "$serverTypeChoice" == "2" ]; then
    echo "Will configure storage for Cluster..."
    isClusterNode="Y"
else
    echo "Invalid choice. Exiting installer..."
    exit 1
fi
echo
# If cluster node, verify cluster information
clusterName=""
clusterNodeCount=0
isFirstClusterNode=false
clusterNodeList=()
if [ "$isClusterNode" == "Y" ]; then
    if ! pvecm status &>/dev/null; then
        echo "ERROR: This node is NOT part of a Proxmox cluster. Exiting..."
        exit 1
    fi
    
    clusterName=$(pvecm status | awk -F ': ' '/Name/ {print $2}' | xargs)
    clusterNodeCount=$(pvecm status | awk -F ': ' '/Nodes/ {print $2}' | xargs)
    clusterNodeList=($(pvecm nodes | awk 'NR > 4 {print $3}'))

    read -p "Is this node the first node to be configured for SAN Storage in cluster '$clusterName'? (Y/N): " isFirstClusterNode
    
fi


# Install needed packages
echo "##############################"
echo "# Installing needed packages #"
echo "##############################"
apt update && apt install vim multipath-tools* parted dlm-controld gfs2-utils -y
echo

# Correcting DLM configuration for cluster
echo "##################################################"
echo "# Correcting DLM for Cluster #"
echo "##################################################"
grep -qxF 'DLM_CONTROLD_OPTS="--enable_fencing 0"' /etc/default/dlm || echo 'DLM_CONTROLD_OPTS="--enable_fencing 0"' >> /etc/default/dlm
echo "systemctl restart dlm"
systemctl restart dlm
echo "systemctl stop dlm"
systemctl stop dlm
echo "rmmod gfs2"
rmmod gfs2
echo "rmmod dlm"
rmmod dlm
echo "Sleeping for 3 seconds..."
sleep 3
echo "systemctl restart udev"
systemctl restart udev
echo "Sleeping for 3 seconds..."
sleep 3
echo "systemctl start dlm"
systemctl start dlm
echo

# Print WWNs of the server
echo "##################################################"
echo "# Printing list of Fibre Channel WWPNs of system #"
echo "##################################################"
cat /sys/class/fc_host/host*/port_name
echo

# Waiting for user to zone and attached FC volumes
read -p "Hit enter to continue once the volumes are attached to the server..."
echo
verify_disks_found

# # Rescan SCSI Bus to detect the new volume(s)
# echo "#########################################"
# echo "# Rescanning SCSI Bus to find new disks #"
# echo "#########################################"
# rescan-scsi-bus.sh -i && rescan-scsi-bus.sh -a
# echo

# # List discovered volume(s) and ask if reboot is needed
# echo "#######################################"
# echo "# Listing current disks of the system #"
# echo "#######################################"
# lsblk
# echo
# read -p "Are SAN volume(s) found? (Y/N): " foundVolumes
# if [ "$foundVolumes" != "Y" ] && [ "$foundVolumes" != "y" ]; then
# 	read -p "Do you want to reboot this system to find volumes? (Y/N): " confirmReboot
# 	if [ "$confirmReboot" == "Y" ] || [ "$confirmReboot" == "y" ]; then
# 		reboot
# 	else
# 		echo "Exiting install now..."
# 		exit 1
#     fi
# fi
# echo

# Creating list of Hitachi SAN Disks and Non-Hitachi Disks on the system
echo "#########################################################################"
echo "# Getting list of Hitachi SAN Disks and Non-Hitachi Disks on the system #"
echo "#########################################################################"

# Create array to hold disk IDs and array to hold seen disk Ids
diskIdArray=()
blackListDiskIdArray=()
declare -A seenIds

# Get list of WWN IDs of volume(s)
for disk in $(ls /dev/sd?); do
	if [[ -b "$disk" ]]; then
		diskId="$(/lib/udev/scsi_id -g -u -d $disk)"
		if [[ "${diskId:0:9}" == "360060e80" ]]; then
			# echo "Found disk: $diskId"
			if [[ -z "${seenIds[$diskId]}" ]]; then
				# echo "Found unique disk: $diskId"
				diskIdArray+=("$diskId")
				seenIds[$diskId]=1
			fi
        else
            if [[ -z "${seenIds[$diskId]}" ]]; then
				# echo "Found unique disk: $diskId"
				blackListDiskIdArray+=("${diskId#*_}")
				seenIds[$diskId]=1
			fi
		fi
	fi
done

diskNames=()
# Print found Volume IDs
echo "Found following Hitachi SAN Volume IDs and enabled them for multipath support:"
for diskId in ${diskIdArray[@]}; do
	echo -e "\t$diskId"
    correctVolName="N"
    read -p $"\tEnable multipathing support for disk '$diskId'? (Y/N): " enableMultipath
    if [[ "$enableMultipath" != "Y" && "$enableMultipath" != "y" ]]; then
        while [[ "$correctVolName" != "Y" && "$correctVolName" != "y" ]]; do
            read -p $'\tEnter '"name for volume $diskId [default: vol${#diskNames[@]}]: " volName
            volName=${volName:-vol${#diskNames[@]}}
            read -p $'\tVolume name '"'$volName' was entered. Correct? (Y/N): " correctVolName
        done
        diskNames+=("$volName")
        multipath -a $diskId >> /dev/null 2>&1
    else
        echo "Skipping multipath configuration for volume '$diskId'"
    fi    
done
echo

echo "Found following Non-SAN Volume IDs:"
for diskId in ${blackListDiskIdArray[@]}; do
	echo -e "\t$diskId"
done
echo

# Creating multipath.conf file
echo "####################################"
echo "# Generating Multipath Config File #"
echo "####################################"

defaultsSection='defaults {
    polling_interval 10
    path_selector "round-robin 0"
    path_grouping_policy multibus
    uid_attribute ID_SERIAL
    prio alua
    path_checker readsector0
    rr_min_io 100
    max_fds 8192
    rr_weight priorities
    failback immediate
    no_path_retry fail
    user_friendly_names yes
    find_multipaths yes
}'

devicesSection='devices {
    device {
        vendor "HITACHI"
        product "OPEN-.*"
        path_grouping_policy multibus
        path_selector "round-robin 0"
        path_checker tur
        features "0"
        hardware_handler "0"
        prio const
        rr_weight uniform
        rr_min_io 1000
        rr_min_io_rq 1
        fast_io_fail_tmo 5
        dev_loss_tmo 10
        no_path_retry fail
    }
}'

blacklistSectionWWIDEntries=()
if [ ${#blackListDiskIdArray[@]} -gt 0 ]; then
    echo "Adding Non-SAN disks to multipath blacklist"
    for diskId in ${blackListDiskIdArray[@]}; do
        wwidEntry=$'\twwid '"${diskId}"
        echo "$wwidEntry"
        blacklistSectionWWIDEntries+=("$wwidEntry")
    done
    echo
fi

blacklistSection=("blacklist {")
for entry in "${blacklistSectionWWIDEntries[@]}"; do
    blacklistSection+=("$entry")
done

blacklistSection+=($'\tdevnode "^(ram|raw|loop|fd|md|dm-|sr|scd|st)[0-9]*"')
blacklistSection+=($'\tdevnode "^hd[a-z]"')
blacklistSection+=('}')

# echo "Printing blacklist section:"
# for entry in "${blacklistSection[@]}"; do
#     echo "${entry}"
# done

# Create Multipath section
multipathSection=("multipaths {")
for ((i=0; i < ${#diskIdArray[@]}; i++)); do
    multipathSection+=($'\tmultipath {')
    multipathSection+=($'\t\twwid'" ${diskIdArray[$i]}")
    multipathSection+=($'\t\talias'" ${diskNames[$i]}")
    multipathSection+=($'\t}')
done
multipathSection+=($'\t# End of multipath devices')
multipathSection+=("}")

# echo "Printing multipaths section:"
# for entry in "${multipathSection[@]}"; do
#     echo "${entry}"
# done
# echo

# Compile all multipath.conf file
multipath_config=$defaultsSection
for entry in "${blacklistSection[@]}"; do
    multipath_config+=$'\n'$entry
done
for entry in "${multipathSection[@]}"; do
    multipath_config+=$'\n'$entry
done
multipath_config+=$'\n'$devicesSection

# echo Printing full Multipath Config File
echo "${multipath_config}"
echo

read -p "WARNING! This will create/overwrite '/etc/multipath.conf'. Do you want to continue? (Y/N): " continueFlag
if [[ "$continueFlag" != "Y" && "$continueFlag" != "y" ]]; then
    echo "Exiting installer now..."
    exit
fi

echo "${multipath_config}" > /etc/multipath.conf

# Restarting Multipath and verify volumes have the new names
echo "Restarting Multipath to apply new configuration..."
systemctl daemon-reload
systemctl start multipathd
systemctl restart multipathd
echo "Sleeping for 20 seconds to allow multipath to settle..."
sleep 10
multipath -r
sleep 10
echo "Verifying Hitachi SAN Volumes with new names..."
multipath -ll
echo
read -p "Are all Hitachi SAN Volumes showing with correct names? (Y/N): " correctMultipathNames
if [[ "$correctMultipathNames" != "Y" && "$correctMultipathNames" != "y" ]]; then
    echo "Exiting installer now..."
    exit 1
fi
echo

# Updating system to detect and use new SAN volumes on boot
update-initramfs -u -k all

# If this is a cluster node...
if [[ "$isClusterNode" == "Y" ]]; then
    # If this is the first cluster node, create the GFS2 cluster filesystems
    if [[ "$isFirstClusterNode" == "Y" || "$isFirstClusterNode" == "y" ]]; then
        # Verify the cluster node count is correct
        read -p "Cluster has $clusterNodeCount nodes. Is this correct? (Y/N): " verifyClusterNodeCount
        if [ "$verifyClusterNodeCount" != "Y" ] && [ "$verifyClusterNodeCount" != "y" ]; then
            read -p "Enter correct number of nodes in cluster: " clusterNodeCount
        fi
        echo

        # Create GFS2 filesystems on each volume
        for diskName in ${diskNames[@]}; do
            make_gpt_partition "/dev/mapper/$diskName"
            echo "Creating GFS2 filesystem on /dev/mapper/$diskName-part1 with cluster table name '$clusterName:$diskName' and $clusterNodeCount journals..."
            mkfs.gfs2 -t $clusterName:$diskName -j $clusterNodeCount -J 1024 /dev/mapper/$diskName-part1 -O
            echo
        done
    else # Skip GFS2 creation if not first cluster node
        echo "Not first cluster node. Skipping GFS2 cluster creation..."
    fi

    # Create mount points, systemd mount services, and enable/start service for each volume
    for diskName in ${diskNames[@]}; do
        mnt="/mnt/$diskName"
        partition="/dev/mapper/$diskName-part1"
        echo "Creating directory '$mnt' to mount the volume..."
        mkdir -p $mnt
        echo Creating service to mount volume on boot...
        uuid=$(blkid $partition | sed -n 's/.*UUID=\"\([^\"]*\)\".*/\1/p')
        escaped_mnt=$(systemd-escape -p --suffix=mount $mnt)

        serviceText="[Unit]
Description = Mount GFS2 Fibre Channel LUN $diskName
Wants=multipathd.service dlm.service
After=multipathd.service dlm.service

[Mount]
What=/dev/disk/by-uuid/$uuid
Where=$mnt
Type=gfs2
Options=_netdev,acl

[Install]
WantedBy=multi-user.target
"

        echo "$serviceText" > /etc/systemd/system/$escaped_mnt
        systemctl daemon-reload
        systemctl enable $escaped_mnt
        systemctl start $escaped_mnt
        echo
    done

    if [[ "$isFirstClusterNode" == "Y" || "$isFirstClusterNode" == "y" ]]; then
        # Stopping here until user verifies that all nodes have the storage properly configured
        read -p "STOP HERE!: Before proceeding, run this script on all other cluster nodes to configure them. Hit enter to continue ONLY once all nodes prompt you do so..."

        # Create Proxmox Storage entries for each volume
        nodesListCSV=$(IFS=, ; echo "${clusterNodeList[*]}")
        for diskName in ${diskNames[@]}; do
            mnt="/mnt/$diskName"
            echo "Creating Proxmox Storage Entry for GFS2 volume mounted at $mnt ..."
            pvesm add dir $diskName --path $mnt --create-base-path --create-subdirs --shared 1 --nodes $nodesListCSV --content images,rootdir,vztmpl,backup,iso,snippets,import --snapshot-as-volume-chain 1
        done
        echo

        echo "Finished configuring this node and the cluster storage!"
    else
        echo "Not first cluster node. Skipping Proxmo"
        echo
        echo "Finished configuring this node!"
        echo "Please repeat this script on all other cluster nodes to configure their storage. Then continue this script on the first node to create Proxmox storage entries."
    fi
    

else # Else if you are a standalone server
    echo "Standalone server detected. Creating XFS File Systems..."
    for diskName in ${diskNames[@]}; do
        # Create XFS File System
        echo "Creating XFS filesystem on /dev/mapper/$diskName"
        mkfs.xfs /dev/mapper/$diskName
        echo

        # Create mount point, systemd mount service, and enable/start service
        mnt="/mnt/$diskName"
        echo "Creating directory '$mnt' to mount the volume..."
        mkdir -p $mnt
        echo "Creating service to mount volume on boot..."
        uuid=$(blkid /dev/mapper/$diskName | sed -n 's/.*UUID=\"\([^\"]*\)\".*/\1/p')
        escaped_mnt=$(systemd-escape -p --suffix=mount $mnt)

        serviceText="[Unit]
Description = Mount GFS2 Fibre Channel LUN $diskName
Wants=multipathd.service dlm.service
After=multipathd.service dlm.service

[Mount]
What=/dev/disk/by-uuid/$uuid
Where=$mnt
Type=xfs
Options=_netdev,acl

[Install]
WantedBy=multi-user.target
"

        echo "$serviceText" > /etc/systemd/system/$escaped_mnt
        systemctl daemon-reload
        systemctl enable $escaped_mnt
        systemctl start $escaped_mnt
        echo

        # Create Proxmox Storage entries for each volume
        echo "Proxmox storage creation..."
        pvesm add dir $diskName --path $mnt --create-base-path --create-subdirs --nodes $currentNodeName --content images,rootdir,vztmpl,backup,iso,snippets,import --snapshot-as-volume-chain 1
    done

    echo "Finished configuring standalone server storage!"
fi