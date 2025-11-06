import sys, os, json, re, subprocess, argparse, socket, time
from datetime import datetime, timedelta
from pathlib import Path

def main(config: dict = None):
    hostname = socket.gethostname()
    serverType = getServerType()
    cluster_info = {}
    if serverType == 'cluster':
        cluster_info = get_cluster_information()
    handleNeededPackages()
    # configure_dlm_for_cluster()
    print_wwpn()
    print()
    input("Hit enter to continue once the volumes are attached to the server...")
    verify_disks_found()
    selected_volumes, rejected_volumes = select_disks_for_multipathing()
    selected_volumes = configure_multipath_for_volumes(selected_volumes)

    
    # Currently no Python implementation, using bash script
    # script_path = os.path.join(os.path.dirname(__file__), 'install.sh')
    # process = subprocess.Popen(['bash', script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # stdout, stderr = process.communicate()
    # if process.returncode != 0:
    #     print(f"Error executing install script: {stderr.decode()}", file=sys.stderr)
    #     sys.exit(process.returncode)
    # print(stdout.decode())
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
            'is_first_cluster_node': bool,
            'cluster_node_list': list
        }
    """
    cluster_info = {
        'cluster_name': "",
        'cluster_node_count': 0,
        'is_first_cluster_node': False,
        'cluster_node_list': []
    }
    
    # Check if node is part of a Proxmox cluster
    try:
        result = subprocess.run(
            ['pvecm', 'status'],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse cluster name
        for line in result.stdout.split('\n'):
            if 'Name:' in line:
                cluster_info['cluster_name'] = line.split(':', 1)[1].strip()
            elif 'Nodes:' in line:
                try:
                    cluster_info['cluster_node_count'] = int(line.split(':', 1)[1].strip())
                except ValueError:
                    cluster_info['cluster_node_count'] = 0
        
        # Get cluster node list
        nodes_result = subprocess.run(
            ['pvecm', 'nodes'],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse node list (skip first 4 lines of header)
        lines = nodes_result.stdout.split('\n')
        for line in lines[4:]:  # Skip header lines
            parts = line.split()
            if len(parts) >= 3:
                cluster_info['cluster_node_list'].append(parts[2])

        print(f"\tCluster Name: {cluster_info['cluster_name']}")
        print(f"\tCluster Node Count: {cluster_info['cluster_node_count']}")
        print(f"\tCluster Nodes: {str.join(", ", cluster_info['cluster_node_list'])}")
        
        # Ask if this is the first node to be configured
        cluster_name = cluster_info['cluster_name']
        is_first = ask_yes_no(
            f"\nIs this node the first node to be configured for SAN Storage in cluster '{cluster_name}'?"
        )
        cluster_info['is_first_cluster_node'] = is_first
        
    except subprocess.CalledProcessError:
        print("ERROR: This node is NOT part of a Proxmox cluster. Exiting...")
        sys.exit(1)
    except FileNotFoundError:
        print("ERROR: pvecm command not found. Is Proxmox VE installed? Exiting...")
        sys.exit(1)
    
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
    try:
        result = subprocess.run(
            ['dpkg', '-s', package_name],
            capture_output=True,
            text=True,
            check=False
        )
        # dpkg -s returns 0 if installed, 1 if not
        return result.returncode == 0
    except FileNotFoundError:
        print("dpkg not found - not a Debian system?")
        return False
    
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
    
    # Check if apt update is needed
    if should_update_apt(update_threshold_hours) or force_update:
        print("Updating apt cache...")
        try:
            result = subprocess.run(
                ['apt-get', 'update', '-y'],
                capture_output=True,
                text=True,
                check=True
            )
            print("Apt cache updated successfully")
        except subprocess.CalledProcessError as e:
            print(f"Error updating apt cache: {e.stderr}")
            return False
    else:
        print("Apt cache is recent, skipping update")
    
    # Check if package is already installed
    if is_package_installed(package_name):
        print(f"{package_name} is already installed")
        return True
    
    # Install the package
    print(f"Installing {package_name}...")
    try:
        result = subprocess.run(
            ['apt-get', 'install', '-y', package_name],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"{package_name} installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error installing {package_name}: {e.stderr}")
        return False


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
    dlm_config_file = "/etc/default/dlm"
    dlm_config_line = 'DLM_CONTROLD_OPTS="--enable_fencing 0"'
    
    try:
        # Check if the line already exists in the file
        line_exists = False
        try:
            with open(dlm_config_file, 'r') as f:
                if dlm_config_line in f.read():
                    line_exists = True
        except FileNotFoundError:
            pass  # File doesn't exist, will be created
        
        # Add the line if it doesn't exist
        if not line_exists:
            with open(dlm_config_file, 'a') as f:
                f.write(f"{dlm_config_line}\n")
            print(f"Added configuration to {dlm_config_file}")
        else:
            print(f"Configuration already exists in {dlm_config_file}")
    
    except Exception as e:
        print(f"Error updating DLM configuration: {e}")
        return False
    
    # Restart dlm service
    print("RUNNING: systemctl restart dlm")
    try:
        subprocess.run(['systemctl', 'restart', 'dlm'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error restarting dlm: {e}")
        return False
    
    # Stop dlm service
    print("RUNNING: systemctl stop dlm")
    try:
        subprocess.run(['systemctl', 'stop', 'dlm'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error stopping dlm: {e}")
        return False
    
    # Remove gfs2 module
    print("RUNNING: rmmod gfs2")
    try:
        subprocess.run(['rmmod', 'gfs2'], check=True)
    except subprocess.CalledProcessError:
        print("Warning: Could not remove gfs2 module (may not be loaded)")
    
    # Remove dlm module
    print("RUNNING: rmmod dlm")
    try:
        subprocess.run(['rmmod', 'dlm'], check=True)
    except subprocess.CalledProcessError:
        print("Warning: Could not remove dlm module (may not be loaded)")
    
    # Sleep for 3 seconds
    print("Sleeping for 3 seconds...")
    time.sleep(3)
    
    # Restart udev service
    print("RUNNING: systemctl restart udev")
    try:
        subprocess.run(['systemctl', 'restart', 'udev'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error restarting udev: {e}")
        return False
    
    # Sleep for 3 seconds
    print("Sleeping for 3 seconds...")
    time.sleep(3)
    
    # Start dlm service
    print("RUNNING: systemctl start dlm")
    try:
        subprocess.run(['systemctl', 'start', 'dlm'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error starting dlm: {e}")
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


def list_disks():
    """List all available disks on the system."""
    print()
    print("###################")
    print("# Available Disks #")
    print("###################")
    
    try:
        # List block devices
        result = subprocess.run(
            ['lsblk', '-o', 'NAME,TYPE,MODEL,SIZE,WWN'],
            capture_output=True,
            text=True,
            check=True
        )
        print(result.stdout)
    
    except FileNotFoundError:
        print("Error: lsblk command not found")
    except subprocess.CalledProcessError as e:
        print(f"Error listing disks: {e}")


def rescan_disks():
    """Rescan SCSI bus to detect new volumes."""
    print()
    print("#######################")
    print("# Rescanning SCSI Bus #")
    print("#######################")
    
    try:
        # Rescan all SCSI hosts
        result = subprocess.run(
            ['rescan-scsi-bus.sh', '--largelun', '--multipath', '--issue-lip-wait=10', '--alltargets'],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0:
            print("SCSI bus rescanned successfully")
            print(result.stdout)
        else:
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
    
    except FileNotFoundError:
        print("rescan-scsi-bus.sh not found, attempting manual rescan...")
        # Fallback to manual rescan (code above)
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
    
    except Exception as e:
        print(f"Error during SCSI rescan: {e}")
    
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
    try:
        result = subprocess.run(
            ['lsblk', '-d', '-n', '-o', 'NAME,SIZE,MODEL,WWN'],
            capture_output=True,
            text=True,
            check=True
        )
        
        raw_devices = [] # For holding all raw sd devices
        scsi_ids = [] # For holding all scsi_ids.. will be made unique later
        for line in result.stdout.strip().split('\n'):
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

    except subprocess.CalledProcessError as e:
        print(f"Error running lsblk: {e}")
        return []
    except FileNotFoundError:
        print("Error: lsblk command not found")
        return []
    
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

def select_disks_for_multipathing()->None:
    """
    Allow user to select disks for multipathing configuration.
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

def configure_multipath_for_volumes(volumes:list)->dict:
    """
    Asks user to provide an alias for each volume in the list which will be used later to
    created the multipath.conf file

    Args:
        volumes (list): List of volume dictionaries

    Returns:
        list: List of volume dictionaries
    """
    print()
    print("###############################")
    print("# Configure Multipath Volumes #")
    print("###############################")
    for volume in volumes:
        print(f"{volume['scsi_id']:<35}{volume['size']}")
        while True:
            alias = input("\tEnter name for volume alias: ")
            if(ask_yes_no(f"\tIs alias '{alias}' correct?")):
                volume['alias'] = alias
                break

    for volume in volumes:
        print(volume)
    return volumes


if __name__ == "__main__":
   if os.geteuid() != 0:
        print("Error: This function requires root privileges. Run with sudo.")
   else:
        parser = argparse.ArgumentParser(description="Hitachi SAN Installation Conifguration Script created from first Proxmox node setup.")
        parser.add_argument('--config', type=str, help='Path to Hitachi configuration JSON file', required=False)
        args = parser.parse_args()
        config = load_config(args.config) if args.config else None
        main(config)
   
   