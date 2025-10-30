import os, sys, json, re, argparse, shutil

def main() -> None:
    pass

def generate_multipath_config()->None:
    """
    Generates a default multipath configuration dictionary.
    
    Returns:
        dict: The default multipath configuration
    """
    lines = []
    
    multipathConfig = readConfigFile()

    defaultsSection = {
        "polling_interval": 10,
        "path_selector": "\"round-robin 0\"",
        "path_grouping_policy": "multibus",
        "uid_attribute": "ID_SERIAL",
        "prio": "alua",
        "path_checker": "readsector0",
        "rr_min_io": 100,
        "max_fds": 8192,
        "rr_weight": "priorities",
        "failback": "immediate",
        "no_path_retry": "fail",
        "user_friendly_names": "yes",
        "find_multipaths": "yes"
    }

    devicesSection = {
        "device": {
            "vendor": "\"HITACHI\"",
            "product": "\"OPEN-.*\"",
            "path_grouping_policy": "multibus",
            "path_selector": "\"round-robin 0\"",
            "path_checker": "tur",
            "features": "\"0\"",
            "hardware_handler": "\"0\"",
            "prio": "const",
            "rr_weight": "uniform",
            "rr_min_io": 1000,
            "rr_min_io_rq": 1,
            "fast_io_fail_tmo": 5,
            "dev_loss_tmo": 10,
            "no_path_retry": "fail"
        }
    }
    
    # Add defaults section to lines
    lines.append("defaults {")
    for key, value in defaultsSection.items():
        lines.append(f"\t{key} {value}")
    lines.append("}")

    # Add Blacklist section to lines
    lines.append("blacklist {")
    lines.append('\tdevnode "^sd[a-z]"')
    lines.append('\tdevnode "^hd[a-z]"')
    for entry in multipathConfig["multipathData"]["blacklistedVolumes"]:
        lines.append(f"\twwid {entry['wwid']}")
    lines.append("}")

    # Add Multipaths section to lines
    lines.append("multipaths {")
    for key, _ in multipathConfig["multipathData"]["multipathVolumes"].items():
        volume = multipathConfig["multipathData"]["multipathVolumes"][key]
        lines.append("\tmultipath {")
        lines.append(f"\t\twwid {volume['wwid']}")
        lines.append(f"\t\talias {volume['friendlyName']}")
        lines.append("\t}")
    lines.append("\t# # End of multipath devices")
    lines.append("}")

    # Add Devices section to lines    
    lines.append("devices {")
    lines.append("\tdevice {")
    for key, value in devicesSection["device"].items():
        lines.append(f"\t\t{key} {value}")
    lines.append("\t}")
    lines.append("}")

    print("\n".join(lines))

    filename = "/root/hitachi/multipath.conf"
    backup_filename = filename + ".bak"

    # Make backup of multipath.conf file first
    if os.path.exists(filename):
        shutil.copy2(filename, filename + ".bak")
        print(f"Backup created: {backup_filename}")
    else:
        print(f"No existing multipath.conf file found at {filename}. A new file will be created.")
        
    # Write to file (overwrite)
    with open(filename, "w") as f:
        f.write("\n".join(lines))
    
    # return multipath_config


def readConfigFile()->dict:
    """
    Reads the configuration file and returns its contents as a dictionary
    Returns:
        dict: The configuration data
    Raises:
        Exception: If there is an error reading or parsing the file
    """
    configPath = "/opt/hitachi/etc/hitachi_config.json"
    configData = {}
    try:
        with open(configPath, "r") as f:
            configData = f.read()
        configData = json.loads(configData)
    except Exception as e:
        print(f"Error reading config file: {e}")
    finally:
        return configData
    
if __name__ == "__main__":
    config = generate_multipath_config()
    print(json.dumps(config, indent=4))