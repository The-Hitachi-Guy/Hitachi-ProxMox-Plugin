import sys, os, json, re, subprocess, argparse, socket, time
from datetime import datetime, timedelta
from pathlib import Path

def main(config: dict = None):
    hostname = socket.gethostname()
    getServerType()
    handleNeededPackages()
    configure_dlm_for_cluster()
    
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

if __name__ == "__main__":
   if os.geteuid() != 0:
        print("Error: This function requires root privileges. Run with sudo.")
   else:
        parser = argparse.ArgumentParser(description="Hitachi SAN Installation Conifguration Script created from first Proxmox node setup.")
        parser.add_argument('--config', type=str, help='Path to Hitachi configuration JSON file', required=False)
        args = parser.parse_args()
        config = load_config(args.config) if args.config else None
        main(config)
   
   