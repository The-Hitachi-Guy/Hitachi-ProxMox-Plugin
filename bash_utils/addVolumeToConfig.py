import sys, os, json, argparse, re

def main(alias:str, uuid:str)->None:
    configData = readConfigFile()

    # Check if volume already exists
    if uuid in configData["multipathData"]["multipathVolumes"]:
        print(f"Volume with UUID {uuid} already exists in configuration.")
        return
    
    # Create new volume entry
    volumeData = {
        "wwid": uuid,
        "friendlyName": alias,
        "volumeType": "unused"
    }

    # Add new volume to configuration using the volume's UUID as the key
    configData["multipathData"]["multipathVolumes"][uuid] = volumeData
    
    # Write updated configuration back to file
    writeConfigFile(configData)
    print(f"Successfully added volume: {alias} with UUID: {uuid}")

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
    
def writeConfigFile(configData:dict)->None:
    """
    Writes the given configuration data to the configuration file
    Args:
        configData (dict): The configuration data to write
        
    Raises:
        Exception: If there is an error writing the file
    """
    configPath = "/opt/hitachi/etc/hitachi_config.json"
    try:
        with open(configPath, "w") as f:
            f.write(json.dumps(configData, indent=4))
    except Exception as e:
        print(f"Error writing config file: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("alias", help="The alias name for the device without /dev/mapper prefix")
    parser.add_argument("uuid", help="The UUID of the device to add to the configuration")
    args = parser.parse_args()
    main(args.alias, args.uuid)