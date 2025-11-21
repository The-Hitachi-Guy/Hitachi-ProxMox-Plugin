import os, sys, json, re, argparse, shutil
from typing import Any
from pathlib import Path

def main() -> None:
    current_multipath_config = readMultipathConfigFile()
    if current_multipath_config is not None:
        current_multipath_config = parse_multipath_string(current_multipath_config)
        print(json.dumps(current_multipath_config, indent=4))
        print()
        print()
        for device in current_multipath_config.get("devices", {}):
            print(device)
    else:
        pass
        generate_multipath_config()

def generate_multipath_config()->dict:
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
    lines.append("\t# End of multipath devices")
    lines.append("}")

    # Add Devices section to lines    
    lines.append("devices {")
    lines.append("\tdevice {")
    for key, value in devicesSection["device"].items():
        lines.append(f"\t\t{key} {value}")
    lines.append("\t}")
    lines.append("}\n")

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
    
def readMultipathConfigFile()->str:
    """
    Reads the existing multipath configuration file and returns its contents as a string
    Returns:
        str: The contents of the multipath configuration file
    Raises:
        Exception: If there is an error reading the file
    """
    filePath = Path("/etc/multipath.conf")
    content = ""
    if filePath.exists():
        try:
            with open(filePath, "r") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading multipath config file: {e}")
        finally:
            return content
    else:
        return None
    
def parse_multipath_conf(filepath: str) -> dict[str, Any]:
    """
    Parse a multipath.conf file and return a dictionary representation.
    
    Args:
        filepath: Path to the multipath.conf file
        
    Returns:
        Dictionary containing the parsed configuration
    """
    with open(filepath, 'r') as f:
        content = f.read()
    
    return parse_multipath_string(content)

def parse_multipath_string(content: str) -> dict[str, Any]:
    """Parse multipath.conf content from a string."""
    # Remove comments (lines starting with # or inline comments)
    lines = []
    for line in content.split('\n'):
        # Remove inline comments
        line = re.sub(r'#.*$', '', line)
        lines.append(line)
    content = '\n'.join(lines)
    
    return _parse_block(content)

def _parse_block(content: str) -> dict[str, Any]:
    """Parse a block of multipath.conf content."""
    result = {}
    i = 0
    tokens = _tokenize(content)
    
    while i < len(tokens):
        token = tokens[i]
        
        if token == '}':
            break
        elif i + 1 < len(tokens) and tokens[i + 1] == '{':
            # This is a section/block
            section_name = token
            i += 2  # Skip name and '{'
            
            # Find matching closing brace
            block_content, consumed = _extract_block(tokens[i:])
            i += consumed
            
            parsed_block = _parse_block_tokens(block_content)
            
            # Handle multiple sections with same name (e.g., multiple "device" or "multipath")
            if section_name in result:
                if not isinstance(result[section_name], list):
                    result[section_name] = [result[section_name]]
                result[section_name].append(parsed_block)
            else:
                result[section_name] = parsed_block
        elif i + 1 < len(tokens) and tokens[i + 1] not in ('{', '}'):
            # This is a key-value pair
            key = token
            value = tokens[i + 1]
            # Try to convert to appropriate type
            value = _convert_value(value)
            
            if key in result:
                if not isinstance(result[key], list):
                    result[key] = [result[key]]
                result[key].append(value)
            else:
                result[key] = value
            i += 2
        else:
            i += 1
    
    return result

def _tokenize(content: str) -> list[str]:
    """Tokenize the multipath.conf content."""
    tokens = []
    # Match quoted strings, braces, or unquoted words
    pattern = r'"[^"]*"|\'[^\']*\'|[{}]|[^\s{}]+'
    
    for match in re.finditer(pattern, content):
        token = match.group()
        # Remove quotes from quoted strings
        if (token.startswith('"') and token.endswith('"')) or \
           (token.startswith("'") and token.endswith("'")):
            token = token[1:-1]
        tokens.append(token)
    
    return tokens

def _extract_block(tokens: list[str]) -> tuple[list[str], int]:
    """Extract tokens until matching closing brace."""
    depth = 1
    block = []
    i = 0
    
    while i < len(tokens) and depth > 0:
        if tokens[i] == '{':
            depth += 1
        elif tokens[i] == '}':
            depth -= 1
            if depth == 0:
                i += 1
                break
        block.append(tokens[i])
        i += 1
    
    return block, i

def _parse_block_tokens(tokens: list[str]) -> dict[str, Any]:
    """Parse a list of tokens into a dictionary."""
    result = {}
    i = 0
    
    while i < len(tokens):
        token = tokens[i]
        
        if token in ('{', '}'):
            i += 1
            continue
        elif i + 1 < len(tokens) and tokens[i + 1] == '{':
            # Nested section
            section_name = token
            i += 2
            block_content, consumed = _extract_block(tokens[i:])
            i += consumed
            
            parsed_block = _parse_block_tokens(block_content)
            
            if section_name in result:
                if not isinstance(result[section_name], list):
                    result[section_name] = [result[section_name]]
                result[section_name].append(parsed_block)
            else:
                result[section_name] = parsed_block
        elif i + 1 < len(tokens) and tokens[i + 1] not in ('{', '}'):
            # Key-value pair
            key = token
            value = _convert_value(tokens[i + 1])
            
            if key in result:
                if not isinstance(result[key], list):
                    result[key] = [result[key]]
                result[key].append(value)
            else:
                result[key] = value
            i += 2
        else:
            i += 1
    
    return result

def _convert_value(value: str) -> Any:
    """Convert string value to appropriate Python type."""
    # Boolean-like values
    if value.lower() in ('yes', 'true'):
        return True
    if value.lower() in ('no', 'false'):
        return False
    
    # Try integer
    try:
        return int(value)
    except ValueError:
        pass
    
    # Try float
    try:
        return float(value)
    except ValueError:
        pass
    
    return value
    
if __name__ == "__main__":
    main()