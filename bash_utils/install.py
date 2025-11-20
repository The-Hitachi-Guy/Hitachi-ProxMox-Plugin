import sys, os, json, re, subprocess, argparse, socket, time
from datetime import datetime, timedelta
from pathlib import Path

def main(config: dict = None):
    if config:
        hostname = socket.gethostname()
        handleNeededPackages()
    else:
        config = {}
        hostname = socket.gethostname()
        config['serverName'] = socket.gethostname()
        config['isClusterNode'] = False
        serverType = getServerType()
        cluster_info = {}
        if serverType == 'cluster':
            config['isClusterNode'] = True
            cluster_info = get_cluster_information()
            config['clusterConfig'] = get_cluster_information()
        handleNeededPackages()
        # configure_dlm_for_cluster()
        print_wwpn()
        print()
        input("Hit enter to continue once the volumes are attached to the server...")
        verify_disks_found()
        selected_volumes, rejected_volumes = select_disks_for_multipathing()
        mountRoot = get_mount_root()
        selected_volumes = configure_volumes_for_multipath(selected_volumes, mountRoot)

        # for volume in selected_volumes:
        #     print(json.dumps(volume,indent=4))

        hitachi_config = create_config_file(hostname, serverType, selected_volumes, rejected_volumes, mountRoot, cluster_info)
    
    return 0

def load_config(config_path: str) -> dict:
    with open(config_path, 'r') as f:
        return json.load(f)
    
def ask_yes_no(question: str) -> bool:
    """
    Ask a yes/no question and return True for yes, False for no.
    
    Parameters:
    - question: Question to ask the user
    
    Returns:
    - True if user answers yes, False if user answers no
    """
    while True:
        answer = input(f"{question} (Y/N): ").strip().upper()
        if answer in ['Y', 'YES']:
            return True
        elif answer in ['N', 'NO']:
            return False
        else:
            print("Please answer Y or N")

def getServerType() -> str:
    """
    Ask user if the server is standalone or a cluster node.
    
    Returns:
        str: 'standalone' if user selects option 1 and 'cluster' if user selects option 2
    """
    print("\nConfigure this system a standalone server or as a cluster node?")
    print("1. Standalone system")
    print("2. Cluster node")
    
    while True:
        choice = input("Select server type (1 or 2): ").strip()
        
        if choice == '1':
            print("Selected: Standalone system")
            return 'standalone'
        elif choice == '2':
            print("Selected: Cluster node")
            return 'cluster'
        else:
            print("Invalid choice. Please enter 1 or 2.")

def get_cluster_information() -> dict:
    """
    Retrieves Proxmox Cluster information that this node is a part of.
    
    Returns:
        dict: Dictionary with cluster information:
        {
            'cluster_name': str,
            'cluster_node_count': int,
            'first_cluster_node': str,
            'cluster_node_list': list
        }
    """
    cluster_info = {
        'cluster_name': "",
        'cluster_node_count': 0,
        'first_cluster_node': "",
        'cluster_node_list': []
    }
    
    # Check if node is part of a Proxmox cluster
    command = "pvecm status"
    stdout, stderr, success = runCommand(command)
    if not success:
        print("ERROR: This node is NOT part of a Proxmox cluster. Exiting...")
        return cluster_info
    
    # Parse cluster name
    for line in stdout.split('\n'):
        if 'Name:' in line:
            cluster_info['cluster_name'] = line.split(':', 1)[1].strip()
        elif 'Nodes:' in line:
            try:
                cluster_info['cluster_node_count'] = int(line.split(':', 1)[1].strip())
            except ValueError:
                cluster_info['cluster_node_count'] = 0

    # Get cluster node list
    command = "pvecm nodes"
    stdout, stderr, success = runCommand(command)
    if not success:
        print("ERROR: Could not retrieve cluster node list. Exiting...")
        sys.exit(1)
    # Parse node list (skip first 4 lines of header)
    lines = stdout.split('\n')
    for line in lines[4:]:  # Skip header lines
        parts = line.split()
        if len(parts) >= 3:
            node = {}
            node['nodeId'] = parts[0]
            node['nodeName'] = parts[2]
            cluster_info['cluster_node_list'].append(node)

    print(f"\tCluster Name: {cluster_info['cluster_name']}")
    print(f"\tCluster Node Count: {cluster_info['cluster_node_count']}")
    nodeList = []
    
    for node in cluster_info['cluster_node_list']:
        nodeList.append(node['nodeName'])
    nodeString = str.join(", ", nodeList)
    print(f"\tCluster Nodes: {nodeString}")
    
    # Ask if this is the first node to be configured
    cluster_name = cluster_info['cluster_name']
    is_first = ask_yes_no(
        f"\nIs this node the first node to be configured for SAN Storage in cluster '{cluster_name}'?"
    )
    if is_first:
        cluster_info['first_cluster_node'] = socket.gethostname()
    cluster_info['is_first_cluster_node'] = is_first
    
    return cluster_info

def handleNeededPackages():
    """
    Ensures that needed Debian packages are installed to support Hitachi Storage.
    
    Returns:
        bool: True if all packages are installed successfully, False otherwise
    """
    print()
    print("##########################################")
    print("# Ensuring needed packages are installed #")
    print("##########################################")
    packages=["vim", "multipath-tools", "multipath-tools-boot", "parted", "dlm-controld", "gfs2-utils", "git"]
    for package in packages:
        if not is_package_installed(package):
            print(f"Package {package} is not installed. Installing...")
            install_package(package, force_update=False, update_threshold_hours=24)
        else:
            print(f"Package {package} is already installed.")

def is_package_installed(package_name: str) -> bool:
    """
    Check if a Debian package is installed using dpkg.
    
    Args:
        package_name: (str) Name of the package to check
    
    Returns:
        Bool: True if package is installed, False otherwise
    """

    command = f"dpkg -s {package_name}"
    stdout, stderr, success = runCommand(command)
    # dpkg -s returns 0 if installed, 1 if not
    return success

    
def install_package(package_name: str, force_update: bool = False, update_threshold_hours: int = 24) -> bool:
    """
    Install a package on a Debian system using apt.
    
    Args:
        package_name: (str) Name of the package to install
        force_update: (bool) Force apt update even if recently updated
        update_threshold_hours: (int) Hours since last update before updating again

    Returns:
        Bool: True if package was installed successfully, False otherwise
    """
    
    # 1. Check if apt update is needed
    if should_update_apt(update_threshold_hours) or force_update:
        print("Updating apt cache...")
        command = "apt-get update -y"
        stdout, stderr, success = runCommand(command)
        if not success:
            print(f"Error updating apt cache: {stderr}")
            return False
        print("Apt cache updated successfully")

    else:
        print("Apt cache is recent, skipping update")
    
    # 2. Check if package is already installed
    if is_package_installed(package_name):
        print(f"{package_name} is already installed")
        return True
    
    # 3. Install the package
    print(f"Installing {package_name}...")
    command = f"apt-get install -y {package_name}"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error installing {package_name}: {stderr}")
        return False
    print(f"{package_name} installed successfully")
    return True


def should_update_apt(threshold_hours: int = 24) -> bool:
    """
    Check if apt cache should be updated based on last update time.
    
    Args:
        threshold_hours: (int) Number of hours since last update before recommending update
    
    Returns:
        Bool: True if update is recommended, False otherwise
    """
    apt_cache_dir = Path('/var/lib/apt/periodic')
    apt_lists_dir = Path('/var/lib/apt/lists')
    
    # Check the partial directory's modification time as indicator
    if apt_lists_dir.exists():
        try:
            # Get the most recently modified file in apt lists
            files = list(apt_lists_dir.glob('*'))
            if files:
                latest_mtime = max(f.stat().st_mtime for f in files if f.is_file())
                last_update = datetime.fromtimestamp(latest_mtime)
                time_since_update = datetime.now() - last_update
                
                return time_since_update > timedelta(hours=threshold_hours)
        except Exception as e:
            print(f"Could not determine last update time: {e}")
            return True
    
    # If we can't determine, assume update is needed
    return True

def configure_dlm_for_cluster() -> bool:
    """
    Configure DLM (Distributed Lock Manager) for cluster.
    Adds DLM configuration and restarts necessary services.
    
    Returns:
    - True if configuration was successful, False otherwise
    """
    print()
    print("##################################################")
    print("# Correcting DLM for Cluster #")
    print("##################################################")
    
    # Add DLM configuration if not already present
    dlm_config_file_path = Path("/etc/default/dlm")
    dlm_config_line = 'DLM_CONTROLD_OPTS="--enable_fencing 0"'

    # Create config file if it doesn't exist
    if not dlm_config_file_path.exists():
        print(f"Creating DLM configuration file at {dlm_config_file_path}")
        dlm_config_file_path.touch()
    
    # Check to see if DLM config line already exists in the file
    line_exists = False
    try:
        with open(dlm_config_file_path, 'r') as f:
            if dlm_config_line in f.read() or line_exists:
                line_exists = True
    except FileNotFoundError:
        pass  # File doesn't exist, will be created
        
    # Add the line if it doesn't exist
    if not line_exists:
        with open(dlm_config_file_path, 'a') as f:
            f.write(f"{dlm_config_line}\n")
        print(f"Added configuration to {str(dlm_config_file_path)}")
    else:
        print(f"Configuration already exists in {str(dlm_config_file_path)}")
    
    # Restart dlm service
    print("RUNNING: systemctl restart dlm")
    command = "systemctl restart dlm"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error restarting dlm: {stderr}")
        return False
    
    # Stop dlm service
    print("RUNNING: systemctl stop dlm")
    command = "systemctl stop dlm"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error stopping dlm: {stderr}")
        return False
    
    # Remove gfs2 module
    print("RUNNING: rmmod gfs2")
    try:
        subprocess.run(['rmmod', 'gfs2'], check=True)
    except subprocess.CalledProcessError:
        print("Warning: Could not remove gfs2 module (may not be loaded)")
    
    # Remove dlm module
    print("RUNNING: rmmod dlm")
    command = "rmmod dlm"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error removing dlm module: {stderr}")
        return False
    
    # Sleep for 3 seconds
    print("Sleeping for 3 seconds...")
    time.sleep(3)
    
    # Restart udev service
    print("RUNNING: systemctl restart udev")
    command = "systemctl restart udev"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error restarting udev: {stderr}")
        return False
    
    # Sleep for 3 seconds
    print("Sleeping for 3 seconds...")
    time.sleep(3)
    
    # Start dlm service
    print("RUNNING: systemctl start dlm")
    command = "systemctl start dlm"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error starting dlm: {stderr}")
        return False
    
    print()
    print("DLM configuration completed successfully")
    return True

def print_wwpn() -> bool:
    """
    Print the WWPN (World Wide Port Name) of all Fibre Channel HBA ports.
    
    Returns:
        bool: True if WWPNs were found and printed, False otherwise
    """
    print()
    print("##################################################")
    print("# Server WWPN Information #")
    print("##################################################")
    
    fc_host_path = Path('/sys/class/fc_host')
    
    if fc_host_path.exists():
        host_dirs = sorted(fc_host_path.glob('host*'))
        
        if host_dirs:
            print("\nFibre Channel HBA WWPNs:")
            found_wwpn = False
            
            for host_dir in host_dirs:
                wwpn_file = host_dir / 'port_name'
                wwnn_file = host_dir / 'node_name'
                
                try:
                    if wwpn_file.exists():
                        with open(wwpn_file, 'r') as f:
                            wwpn = f.read().strip()
                        
                        # Also get WWNN if available
                        wwnn = ""
                        if wwnn_file.exists():
                            with open(wwnn_file, 'r') as f:
                                wwnn = f.read().strip()
                        
                        # Format WWPN for better readability (remove 0x prefix)
                        wwpn_formatted = wwpn.replace('0x', '').upper()
                        wwnn_formatted = wwnn.replace('0x', '').upper() if wwnn else "N/A"
                        
                        print(f"\n  {host_dir.name}:")
                        print(f"    WWPN: {wwpn_formatted}")
                        print(f"    WWNN: {wwnn_formatted}")
                        
                        found_wwpn = True
                
                except Exception as e:
                    print(f"  Error reading {host_dir.name}: {e}")
            
            if found_wwpn:
                print()
                return True
            else:
                print("  No WWPNs found in /sys/class/fc_host/")
        else:
            print("\nNo Fibre Channel HBA hosts found in /sys/class/fc_host/")

def verify_disks_found() -> bool:
    """
    Verify that SAN volumes are found on the system.
    Prompts user to rescan or reboot if volumes are not found.
    
    Returns:
        bool: True if disks are verified, False otherwise
    """
    disks_verified = False
    
    while not disks_verified:
        list_disks()
        found_volumes = ask_yes_no("Are SAN volume(s) found?")
        
        if found_volumes:
            disks_verified = True
        else:
            preform_rescan_disks = ask_yes_no("Do you want to rescan SCSI bus to find volumes?")
            
            if preform_rescan_disks:
                rescan_disks()
            else:
                confirm_reboot = ask_yes_no("Do you want to reboot this system to find volumes?")

                if confirm_reboot:
                    print("Rebooting system...")
                    try:
                        subprocess.run(['reboot'], check=True)
                    except subprocess.CalledProcessError as e:
                        print(f"Error rebooting system: {e}")
                        return False
                else:
                    print("Exiting install now...")
                    sys.exit(1)
    
    print(file=sys.stderr)
    return True


def list_disks()->None:
    """List all available disks on the system."""
    print()
    print("###################")
    print("# Available Disks #")
    print("###################")
    
    command = 'lsblk -o NAME,TYPE,MODEL,SIZE,WWN'
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error listing disks: {stderr}")
    else:
        print(stdout)

def rescan_disks():
    """Rescan SCSI bus to detect new volumes."""
    print()
    print("#######################")
    print("# Rescanning SCSI Bus #")
    print("#######################")
    
    command = "rescan-scsi-bus.sh --largelun --multipath --issue-lip-wait=10 --alltargets"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error rescanning SCSI bus: {stderr}")
        
        # Try alternative method if rescan-scsi-bus.sh is not available
        print("Attempting manual SCSI rescan...")
        
        # Find all SCSI hosts and rescan them
        from pathlib import Path
        scsi_host_path = Path('/sys/class/scsi_host')
        
        if scsi_host_path.exists():
            for host in scsi_host_path.glob('host*'):
                scan_file = host / 'scan'
                if scan_file.exists():
                    try:
                        with open(scan_file, 'w') as f:
                            f.write('- - -\n')
                        print(f"Rescanned {host.name}")
                    except Exception as e:
                        print(f"Error rescanning {host.name}: {e}")
            
            print("\nManual SCSI rescan completed")
        else:
            print("Error: Cannot find SCSI hosts")
    else:
        print(stdout)
    
    print("\nWaiting for devices to settle...")
    subprocess.run(['sleep', '3'], check=False)

def get_scsi_id_sd_devices() -> list:
    """
    Get list of SCSI IDs, their SD block devices and thier info from lsblk and scsi_id.
    
    Returns:
        list: List of dictionaries with device information
        [
            {
                'scsi_id': str,
                'sd_devices': list:[str],
                'size': str,
                'model': str,
                'wwn': str
            }
        ]
    """
    command = 'lsblk -d -n -o NAME,SIZE,MODEL,WWN'
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error running lsblk: {stderr}")
        return []

    raw_devices = [] # For holding all raw sd devices
    scsi_ids = [] # For holding all scsi_ids.. will be made unique later
    for line in stdout.split('\n'):
        if not line.strip():
            continue
        
        parts = line.split(None, 3)  # Split into max 4 parts
        if len(parts) >= 3:
            device_name = parts[0]
            
            # Filter only sd* devices
            if device_name.startswith('sd'):
                device = {
                    'name': device_name,
                    'size': parts[1] if len(parts) > 1 else 'N/A',
                    'model': parts[2] if len(parts) > 2 else 'N/A',
                    'wwn': parts[3] if len(parts) > 3 else 'N/A',
                    'scsi_id': ""
                }

                scsi_id_result = subprocess.run(
                    ['/lib/udev/scsi_id', '-g', '-u', '-d', f'/dev/{device_name}'],
                    capture_output=True,
                    text=True,
                    check=True
                )
                if scsi_id_result.returncode == 0:
                    print(f"Found SCSI ID for /dev/{device_name}: {scsi_id_result.stdout.strip()}")
                    device['scsi_id'] = scsi_id_result.stdout.strip()
                    scsi_ids.append(device['scsi_id'])
                else:
                    print(f"Warning: Could not get SCSI ID for /dev/{device_name}")
                    print(f"  {scsi_id_result.stderr.strip()}")
                raw_devices.append(device)

    scsi_ids = list(set(scsi_ids))  # Make unique and sort
    scsi_ids.sort()
    scsi_id_sd_devices = []
    
    # Create mapping of scsi_id to sd devices and thier attributes
    for scsi_id in scsi_ids:
        scsi_id_sd_device = {
            'scsi_id': scsi_id,
            'sd_devices': [],
        }

        for device in raw_devices:
            if device['scsi_id'] == scsi_id:
                scsi_id_sd_device['sd_devices'].append(device['name'])
                if "size" not in scsi_id_sd_device:
                    scsi_id_sd_device['size'] = device['size']
                    scsi_id_sd_device['model'] = device['model']
                    scsi_id_sd_device['wwn'] = device['wwn']
        scsi_id_sd_devices.append(scsi_id_sd_device)

    return scsi_id_sd_devices
    
def get_hitachi_and_non_hitachi_volumes_from_scsi_id_sd_devices(scsi_id_sd_devices: list) -> list:
    """
    Filter Hitachi volumes from the list of SCSI ID and SD devices and returns a list of Hitachi volumes and a list of non-Hitachi volumes.
    
    Args:
        scsi_id_sd_devices: (list) List of dictionaries with SCSI ID and SD device info

    Returns:
        tuple: (list:hitachi_volumes_list[dict], list:non_hitachi_volumes_list[dict])
    """
    hitachi_volumes = []
    non_hitachi_volumes = []
    for device in scsi_id_sd_devices:
        if "OPEN-V" in device.get('model', ''):
            hitachi_volumes.append(device)
        else:
            non_hitachi_volumes.append(device)
    return (hitachi_volumes, non_hitachi_volumes)

def select_disks_for_multipathing()->tuple:
    """
    Allow user to select disks for multipathing configuration.

    Returns:
        tuple: (list:selected_volumes_list[dict], list:rejected_volumes_list[dict])
    """
    
    print()
    print("###############################################")
    print("# Select Disks for Multipathing Configuration #")
    print("###############################################")
    

    scsi_id_sd_devices = get_scsi_id_sd_devices()
    hitachi_volumes, non_hitachi_volumes = get_hitachi_and_non_hitachi_volumes_from_scsi_id_sd_devices(scsi_id_sd_devices)
    print()
    print("Excluded disks from Multipathing: ")
    print("-------------------------------------")
    print(f"{'SCSI ID':<50} {'SD Devices':<15} {'Size':<10} {'Model':<20} {'WWN':<20}")
    for disk in non_hitachi_volumes:
        print(f"{disk['scsi_id']:<50} {', '.join(disk['sd_devices']):<15} {disk.get('size', 'N/A'):<10} {disk.get('model', 'N/A'):<20} {disk.get('wwn', 'N/A'):<20}")

    print()
    print("Hitachi Volumes: ")
    print("-------------------------------------")
    print(f"{'':<4}{'SCSI ID':<50} {'SD Devices':<15} {'Size':<10} {'Model':<20} {'WWN':<20}")
    for idx, volume in enumerate(hitachi_volumes):
        print(f"{str(idx+1)+')':<4}{volume['scsi_id']:<50} {', '.join(volume['sd_devices']):<15} {volume.get('size', 'N/A'):<10} {volume.get('model', 'N/A'):<20} {volume.get('wwn', 'N/A'):<20}")

    selected_volumes = []
    while True:
        print("\nCurrent Selected Volumes:")
        for idx, volume in enumerate(selected_volumes):
            print(f"{idx+1:<3}) {volume['scsi_id']}")
        print()
        selected_indexes_raw = input("Enter list of volumes to be added to Multipath List, comma seperated (i.e. 1,2,5,8): ")
        selected_indexes = []
        for entry in selected_indexes_raw.split(','):
            try:
                selected_indexes.append(int(entry.strip())-1)
            except:
                print("Found invalid number entry! Try again...")
                print()
        print("\nFollowing Volumes Selected:")
        print(f"{'SCSI ID':<50} {'SD Devices':<15} {'Size':<10} {'Model':<20} {'WWN':<20}")
        for index in selected_indexes:
            volume = hitachi_volumes[index]
            print(f"{volume['scsi_id']:<50} {', '.join(volume['sd_devices']):<15} {volume.get('size', 'N/A'):<10} {volume.get('model', 'N/A'):<20} {volume.get('wwn', 'N/A'):<20}")
        if(ask_yes_no("\nIs this correct? All other volumes will be excluded from multiapthing!")):
            selected_volumes = []
            rejected_volumes = []
            selected_indexes.sort(reverse=True)
            for index in selected_indexes:
                selected_volumes.append(hitachi_volumes.pop(index))
            selected_volumes.reverse()
            rejected_volumes = non_hitachi_volumes + hitachi_volumes

            # print("\nRejected volumes:")
            # for volume in rejected_volumes:
            #     print(volume['scsi_id'])
            # print()
                
            return selected_volumes, rejected_volumes

def get_mount_root()->str:
    """
    Asks user for the directory to create subdirectories for mounting Hitachi volumes

    Returns:
        str: Filepath to root directory to be used for Hitachi volume mounting
    """
    while True:
        mountRoot = input("Enter file path to root directory for mounting Hitachi volumes (Default: /mnt): ")
        if mountRoot == "":
            mountRoot = "/mnt"
        if ask_yes_no(f"Use '{mountRoot}' as root for mounting Hitachi storage on this system?"):
            mountRoot = Path(mountRoot)
            if Path.exists(mountRoot):
                return str(mountRoot)
            else:
                if ask_yes_no("Directory doesn't exist. Do you want to create it?"):
                    Path.mkdir(mountRoot)
                    return str(mountRoot)

def get_vms()->list:
    """
    Retrieves list of virtual machines from the Proxmox environment

    Returns:
        list (dict): List of VM dictionaries
        [
            {
                'vmId': int,
                'vmName': str
            }
        ]
    """
    # Get list of VMs
    print('Getting list of VMs from the Proxmox cluster')
    command = 'pvesh get /cluster/resources --type vm --output-format json'
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error getting VM list: {stderr}")
        return []

    vms_raw = json.loads(stdout)
        
    vms = []
    for vm_raw in vms_raw:
        vm = {
            'vmId': vm_raw['vmid'],
            'vmName': vm_raw['name'],
            'node': vm_raw['node']
        }
        vms.append(vm)
    return vms

def get_vm_scsi_devices(vm:dict)->list:
    """
    Get list of SCSI devices for a VM

    Args:
        vm: (dict) VM object

    Returns:
        list: (dict) List of SCSI devices
        [
            {
                "scsiNum": int,
                "scsiId": str,
                "device": str
            }
        ]
    """
    print(f"Getting SCSI devices for VM {vm['vmName']}...")
    command = f"pvesh get /nodes/{vm['node']}/qemu/{vm['vmId']}/config --output-format json"
    stdout, stderr, success = runCommand(command)
    if not success:
        print(f"Error getting VM config for VM {vm['vmName']}: {stderr}")
        return []
    
    vm_config = json.loads(stdout)
    scsi_keys = [key for key in vm_config.keys() if (key.startswith('scsi') and not key.endswith('hw'))]
    scsi_devices = []
    for scsi_key in scsi_keys:
        scsi_device = {
            'scsiNum': int(scsi_key[4:]),
            'scsiId': scsi_key,
            'device': vm_config[scsi_key]
        }
        scsi_devices.append(scsi_device)
    return scsi_devices

def configure_volumes_for_multipath(volumes:list, mountRoot:str=None, isCluster=False)->dict:
    """
    Asks user to provide an alias for each volume in the list which will be used later to
    created the multipath.conf file

    Args:
        volumes (list): List of volume dictionaries
        mountRoot (str): Mountpoint root for Hitachi volumes
        isCluster: (bool): True if this system is a cluster node, False otherwise

    Returns:
        list: List of volume dictionaries
    """
    print()
    print("###############################")
    print("# Configure Multipath Volumes #")
    print("###############################")
    for volume in volumes:
        print(f"\n{volume['scsi_id']:<35}Size: {volume['size']}")
        # Get volume alias
        while True:
            alias = input("\tEnter name for volume alias (Do not use spaces nor hyphens - ): ")
            if "-" in alias or " " in alias:
                print("\tError! Spaces and hyphens are not allowed.")
            elif(ask_yes_no(f"\tIs alias '{alias}' correct?")):
                volume['alias'] = alias
                break
        # Get volume usage
        while True:
            usage = input("\tHow will volume be used? (datastore, rdm): ")
            if usage.lower() == "datastore" or usage.lower() == "rdm":
                volume['volumeType'] = usage.lower()
                break
            else:
                print("\tInvalid volume usage!")
        
        # if volume will be used as a datastore
        if volume['volumeType'] == 'datastore':
            if isCluster:
                volume['datastoreInfo'] = {
                    "fileSystem": "gfs2",
                    "mountPoint": mountRoot + "/" + volume['alias'],
                    "datastoreName": volume['alias']
                }
            else:
                volume['datastoreInfo'] = {
                    "fileSystem": "xfs",
                    "mountPoint": mountRoot + "/" + volume['alias'],
                    "datastoreName": volume['alias']
                }
        
        # else the volume will be used as an RDM device
        else:
            rdmInfo = {
                'diskId': "scsi-"+volume['scsi_id']
            }
            vms = get_vms()
            selected_vms = []
            while True:
                print(f"{'':<3}{'VM_ID':<6}{'VM_NAME':<30}")
                for idx, vm in enumerate(vms):
                    print(f"{str(idx+1)+')':<3}{vm['vmId']:<6}{vm['vmName']:<30}")
                print()
                selected_vms_indexes = input("Enter list of VMs the RDM will be attached to, comma seperated (i.e. 1,2,5,8): ")
                selected_vms_indexes = selected_vms_indexes.strip().split(',')
                if len(selected_vms_indexes) > 0:
                    for index in selected_vms_indexes:
                        try:
                            index = int(index.strip())-1
                            selected_vms.append(vms[index])
                        except:
                            print(f"Invalid entry [{index}]... Enter only numbers and commas")

                        
                    
                    # Still need to get what SCSI ID these will be assigned for each VM
                    # I suggest finding out what is the highest SCSI ID needed and then
                    # using that for all VMs

                    first_largest_unused_scsiId = 0
                    for vm in selected_vms:
                        vm_scsi_devices = get_vm_scsi_devices(vm)
                        largest = max(vm_scsi_devices, key=lambda x: x['scsiNum'])['scsiNum']
                        if largest > first_largest_unused_scsiId:
                            first_largest_unused_scsiId = largest + 1

                    for vm in selected_vms:
                        vm['scsiId'] = 'scsi' + str(first_largest_unused_scsiId)

                    rdmInfo['vms'] = selected_vms

                else:
                    print(f"Invalid entry... Enter only numbers and commas")
                volume['rdmInfo'] = rdmInfo
                break

    return volumes

def conifgure_volumes(config:dict)->bool:
    """
    Takes a volume configuration and configures it for use on the system

    Args:
        config: (dict) Conifguration dictionary for the server/cluster which
            includes the volume to be configured

    Returns:
        bool: Ture if the volume was successfully configured. False otherwise.
    """
    # If the volume is to be used as a datastore
    volumeKeys = config.get('multipathData', []).get('multipathVolumes', []).keys()

    for key in volumeKeys:
        volume = config['multipathData']['multipathVolumes'][key]
        
        # If volume is to be used as a datastore
        if volume['volumeType'] == "datastore":
            # 1. Verify Mount Point exists
            mountPoint = Path(volume['datastoreInfo']['mountPoint'])
            if not mountPoint.exists():
                mountPoint.mkdir(parents=True)
            
            # 2. If this is the first node in the cluster, proceed to format the volume
            if config['clusterConfig'].get('firstNode', '') == socket.gethostname() or not config['isClusterNode']:
                command = ""
                if config['isClusterNode']:
                    # Create GFS2 file system on the volume
                    command = f"mkfs.gfs2 -t {config['clusterConfig']['clusterName']}:{volume['datastoreInfo']['datastoreName']} " \
                        f"-j {len(config['clusterConfig']['clusterNodes'])} -J 1024 /dev/mapper/{volume['alias']}"
                else:
                    # Create XFS file system on the volume
                    command = f"mkfs.xfs /dev/mapper/{volume['alias']}"

                stdout, stderr, success = runCommand(command)
                if not success:
                    print("ERROR: Failed to format the volume")
                    print(f"STDERR: {stderr}")
                    return False
                           
            # 3. Get UUID of the new file system
            uuid = ""
            command = f"blkid /dev/mapper/{volume['alias']} | sed -n 's/.*UUID=\"\([^\"]*\)\".*/\1/p'"
            stdout, stderr, success = runCommand(command)
            if not success:
                print("ERROR: Failed to get UUID of the new file system")
                print(f"STDERR: {stderr}")
                return False
            uuid = stdout

            # 4. Create systemd mount unit for the volume
            systemd_content = "[Unit]\n" \
                f"Description = Mount GFS2 Fibre Channel LUN {volume['alias']}\n" \
                "Wants=multipathd.service dlm.service\n" \
                "After=multipathd.service dlm.service\n" \
                "\n" \
                "[Mount]\n" \
                f"What=/dev/disk/by-uuid/{uuid}\n" \
                f"Where={volume['datastoreInfo']['mountPoint']}\n" \
                f"Type={volume['datastoreInfo']['fileSystem']}\n" \
                "Options=_netdev,acl\n" \
                "\n" \
                "[Install]\n" \
                "WantedBy=multi-user.target"
            
            mount_unit_path = ""
            
            command = f"systemd-escape -p --suffix=mount {volume['datastoreInfo']['mountPoint']}"
            stdout, stderr, success = runCommand(command)
            if not success:
                print("ERROR: Failed to escape systemd mount unit path")
                print(f"STDERR: {stderr}")
                return False
            
            mount_unit_path = Path('/etc/systemd/system') / result.stdout.strip()

            with open(mount_unit_path, 'w') as f:
                f.write(systemd_content)
            print(f"Created systemd mount unit at {str(mount_unit_path)}")

            # 5. Enable and start the mount unit
            command = f"systemctl enable {mount_unit_path.name}"
            stdout, stderr, success = runCommand(command)
            if not success:
                print(f"ERROR: Failed to enable mount unit {mount_unit_path.name}")
                print(f"STDERR: {stderr}")
                return False

            command = f"systemctl start {mount_unit_path.name}"
            stdout, stderr, success = runCommand(command)
            if not success:
                print(f"ERROR: Failed to start mount unit {mount_unit_path.name}")
                print(f"STDERR: {stderr}")
                return False

        # Else the volume is to be used as an RDM device
        elif volume['volumeType'] == "rdm":
            for vm in volume['rdmInfo']['vms']:
                
                # If this is the current node where the VM is located
                if vm['node'] == socket.gethostname():
                    # Attach RDM disk to VM
                    command = f"qm set {vm['vm_id']} -{vm['scsi_id']} /dev/disk/by-id/{volume['diskId']}"
                    stdout, stderr, success = runCommand(command)
                    
                    if not success:
                        print(f"ERROR: Failed to add RDM disk to VM {vm['vmName']} ({vm['vmId']})")
                        print(f"STDERR: {stderr}")
                        return False
                    
                    # Verify RDM disk is added
                    if stdout.split()[0] == "update":
                        return True
                    else:
                        return False

def create_config_file(hostname:str, servertype:str, multipath_volumes:list, excluded_volumes:list, mount_point:str, cluster_info:dict={})->dict:
    """
    Creates JSON config file to be used by this node or other nodes to generate multipath.conf files

    Args:
        hostname: (str) Host name of the server
        servertype: (str) "standalone" or "cluster"
        multipath_volumes: (list->dict) List of volumes to enable and configure multipath on
        excluded_volumes: (list->dict) List of volumes to remove or prevent multipath services on
        mount_point: (str) Mount point on the system where Hitachi volumes will be mounted
        cluster_info: (dict): Information of the Proxmox Cluster and its cluster nodes. Defualt is blank dict

    Returns:
        dict: "hitachi_config.json" for this server
    """
    
    # Get config file path
    scriptPath = Path(__file__).parent.resolve()
    configFilePath = scriptPath.parents[2] / "config" / 'hitachi_config.json'

    # Create config directory if it doesn't exist
    if not configFilePath.parent.exists():
        configFilePath.parent.mkdir(parents=True)
    
    # Begin creating config dictionary
    hitachi_config = {
        'serverName': hostname,
        'mountRoot': mount_point,
        'isClusterNode': servertype=='cluster',
        'clusterConfig': {}
    }

    # If there is cluster info, add it to the config
    if cluster_info:
        hitachi_config['clusterConfig'] = {
            "clusterName": cluster_info['cluster_name'],
            "clusterNodes": cluster_info['cluster_node_list'],
            "firstNode": cluster_info['first_cluster_node']
        }

    # Add multipath volume info
    multipathVolumes = {}
    
    # For each volume, create the multipath volume entry
    for volume in multipath_volumes:
        # Add basic volume info
        multipathVolume = {
            'scsiId': volume['scsi_id'],
            'alias': volume['alias'],
            'volumeType': volume['volumeType']
        }
        
        # if datastore, add datastore info
        if volume['volumeType'] == 'datastore':
            multipathVolume['datastoreInfo'] = volume['datastoreInfo']
        
        # Else if RDM, add RDM info and remove refereces to nodes from VM entries
        else:
            multipathVolume['rdmInfo'] = volume['rdmInfo']
            for vm in multipathVolume['rdmInfo']['vms']:
                vm.pop('node', None)  # Remove node info from VM dict
        
        # Add volume to multipathVolumes dict
        multipathVolumes[volume['scsi_id']] = multipathVolume

    # Create multipathData entry
    multipathData = {"multipathVolumes": multipathVolumes, "blacklistedVolumes": excluded_volumes}

    # Complete hitachi_config dictionary
    hitachi_config['multipathData'] = multipathData

    # Write config to JSON file
    with open(configFilePath, 'w') as f:
        json.dump(hitachi_config, f, indent=4)

    # Return the created config
    return hitachi_config

def runCommand(command:str)->tuple:
    """
    Runs a shell command

    Args:
        command: (str) Command to run

    Returns:
        tuple:
            str:stdout
            str:stderr
            bool: True if command ran successfully, false otherwise
    """
    print(f"RUNNING: {command}")
    try:
        result = subprocess.run(command.split(), check=True)
        return result.stdout.strip(), result.stderr.strip(), result.returncode == 0
    except subprocess.CalledProcessError as e:
        print(f"Error running command '{command}': {e}")
        return "", e, False
    except FileNotFoundError as e:
        print(f"ERROR: {command.split()[0]} command not found. Exiting...")
        return "", e, False
    except Exception as e:
        print(f"ERROR: '{command}' threw and error!\n{e}")
        return "", e, False

if __name__ == "__main__":
   if os.geteuid() != 0:
        print("Error: This function requires root privileges. Run with sudo.")
   else:
        parser = argparse.ArgumentParser(description="Hitachi SAN Installation Conifguration Script created from first Proxmox node setup.")
        parser.add_argument('--config', type=str, help='Path to Hitachi configuration JSON file', required=False)
        args = parser.parse_args()
        config = load_config(args.config) if args.config else None
        main(config)
   
   