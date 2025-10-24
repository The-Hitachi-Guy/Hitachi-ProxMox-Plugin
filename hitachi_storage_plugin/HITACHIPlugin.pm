package PVE::Storage::Custom::HITACHIPlugin;

use strict;
use warnings;
use Carp qw( confess );
use IO::File;
use JSON::XS qw( decode_json );
use Data::Dumper;
use REST::Client;
use Storable qw(lock_store lock_retrieve);
use UUID;

use LINBIT::Linstor;
use LINBIT::PluginHelper
  qw(valid_legacy_name valid_uuid_name valid_cloudinit_name valid_state_name valid_snap_name valid_pvc_name valid_fleece_name valid_name get_images);

use PVE::Tools qw(run_command trim);
use PVE::INotify;
use PVE::Storage;
use PVE::Storage::Plugin;
use PVE::JSONSchema qw(get_standard_option);

use base qw(PVE::Storage::Plugin);

my $PLUGIN_VERSION = '0.0.1';




# *****************
# * Configuration *
# *****************
my $default_server_name = get_this_server_name();
my $default_mount_point = "/mnt"

my $config_location = "/usr/share/perl5/PVE/Storage/Custom/HITACHIConfig.json";
my $hitachi_config = undef;
my $serverName = undef;
my $mountRoot = undef;
my $isClusterNode = undef;
my $clusterName = undef;
my @clusterNodes = undef;
my $clusterNodeCount = undef;
my $friendlyName = undef;

sub api {
    # PVE 5:   APIVER  2
    # PVE 6:   APIVER  3
    # PVE 6:   APIVER  4 e6f4eed43581de9b9706cc2263c9631ea2abfc1a / volume_has_feature
    # PVE 6:   APIVER  5 a97d3ee49f21a61d3df10d196140c95dde45ec27 / allow rename
    # PVE 6:   APIVER  6 8f26b3910d7e5149bfa495c3df9c44242af989d5 / prune_backups (fine, we don't support that content type)
    # PVE 6:   APIVER  7 2c036838ed1747dabee1d2c79621c7d398d24c50 / volume_snapshot_needs_fsfreeze (guess we are fine, upstream only implemented it for RDBPlugin; we are not that different to let's say LVM in this regard)
    # PVE 6:   APIVER  8 343ca2570c3972f0fa1086b020bc9ab731f27b11 / prune_backups (fine again, see APIVER 6)
    # PVE 7:   APIVER  9 3cc29a0487b5c11592bf8b16e96134b5cb613237 / resets APIAGE! changes volume_import/volume_import_formats
    # PVE 7.1: APIVER 10 a799f7529b9c4430fee13e5b939fe3723b650766 / rm/add volume_snapshot_{list,info} (not used); blockers to volume_rollback_is_possible (not used)
    # PVE 8.4: APIVER 11 e2dc01ac9f06fe37cf434bad9157a50ecc4a99ce / new_backup_provider/sensitive_properties; backup provider might be interesting, we can look at it later
    # PVE 9:   APIVER 12 280bb6be777abdccd89b1b1d7bdd4feaba9af4c2 / qemu_blockdev_options/rename_snapshot/get_formats
    #
    # we support all (not all features), we just have to be careful what we return
    # as for example PVE5 would not like a APIVER 3

    my $tested_apiver = 12;

    my $apiver = PVE::Storage::APIVER;
    my $apiage = PVE::Storage::APIAGE;

    # the plugin supports multiple PVE generations, currently we did not break anything, tell them what they want to hear if possible
    if ($apiver >= 2 and $apiver <= $tested_apiver) {
        return $apiver;
    }

    # if we are still in the APIAGE, we can still report what we have
    if ($apiver - $apiage < $tested_apiver) {
        return $tested_apiver;
    }

    # fallback that worked a very very long time ago, nowadays useless, as the core does APIVER - APIAGE checking
    return 3;
}

# we have to name it drbd, there is a hardcoded 'drbd' in Plugin.pm
sub type {
    return 'hitachi-shared-dir';
}

sub plugindata {
    return {
        content => [ 
            {
                images => 1,
                rootdir => 1,
                iso => 1,
                vztmpl => 1,
                backup => 1,
                snippets => 1,
                none => 1,
                import => 1,
            },
            { images => 1, rootdir => 1 }
        ],
        format => [{ raw => 1, qcow2 => 1, vmdk => 1, subvol => 1 }, 'raw'],
        'sensitive-properties' => {},
    };
}

sub properties {
    return {
        serverName => {
            description => "Name of this server",
            type        => 'string',
            default     => $default_server_name,
        },
        mountPoint => {
             description => "Mount point where multipath directories are mounted on the server",
             type        => 'string',
             default     => $default_mount_point,
        }
    };
}

sub options {
    return {
        path => { fixed => 1 },
        'content-dirs' => { optional => 1 },
        nodes => { optional => 1 },
        shared => { optional => 1 },
        disable => { optional => 1 },
        'prune-backups' => { optional => 1 },
        'max-protected-backups' => { optional => 1 },
        content => { optional => 1 },
        format => { optional => 1 },
        mkdir => { optional => 1 },
        'create-base-path' => { optional => 1 },
        'create-subdirs' => { optional => 1 },
        is_mountpoint => { optional => 1 },
        bwlimit => { optional => 1 },
        preallocation => { optional => 1 },
        'snapshot-as-volume-chain' => { optional => 1, fixed => 1 },
    };
}

sub activate_storage {

}

sub deactivate_storage {

}




# ******************
# * Volume Section *
# ******************
sub path {

}

sub list_images {

}

sub create_image {

}

sub free_image {

}

sub clone_image {

}

sub resize_image {

}

sub move_image {

}




# ********************
# * Snapshot Section *
# ********************
sub volume_snapshot {

}

sub volume_snapshot_rollback {

}

sub volume_snapshot_delete {

}

sub volume_has_features {

}




# =====================
# = Utility Functions =
# =====================
sub parse_volname {

}

sub get_sudir {

}

sub volume_size_info {

}

sub check_connection {

}

# ************************************************************************
# This will install the needed packages to support Hitachi storage and 
# cluster file system
# Returns:
#   1 (succeeded) if all packages were installed and 0 (failed) otherwise
# ************************************************************************
sub install_needed_packages {
    # Variable to hold if all installations were successful
    # Will be changed to false if any package fails to install
    my $succeeded = 1;
    
    # Updating the apt cache of packages
    my $cmd = "apt update";
    my $result = system($cmd);
    
    # Foreach needed package, install it
    my @needed_packages = ('multipath-tools', 'dlm-controld', 'gfs2-utils');
    foreach my $pkg in (@needed_packages) {
        # Create install command, run it and get its result
        my $cmd = "apt-get install -y $pkg";
        my $result = system($cmd);
        
        # State whether the install of the package was successful or not
        if ($result == 0) {
            print "Installation of $pkg successful!\n";
        } else {
            warn "Installation of $pkg failed.\n";
            succeeded = 0;
        }
    }

    return $succeeded;
}

# ************************************************************************
# Checks if all the needed OS packages to support Hitachi and cluster 
# filesystem are installed. 
# Returns:
#   1 (true) if all packages are installed and 0 (false) otherwise
# ************************************************************************
sub check_needed_packages {
    my @needed_packages = ('multipath-tools', 'dlm-controld', 'gfs2-utils');
    foreach my $pkg (@needed_packages) {
        # Run dpkg-query quietly
        my $status = system("dpkg-query -W -f='\${Status}' $pkg 2>/dev/null | grep -q 'install ok installed'");

        if ($status != 0) {
            warn "Package not installed: $pkg\n";
            return 0;  # false
        }
    }
    return 1;  # true
}

# ************************************************************************
# Gets list of missing packages to support Hitachi and cluster filesystem
# Returns:
#   Array(string): Arrays of missing package names
# ************************************************************************
sub get_missing_needed_packages {
    my @missingPkgs;
    my @needed_packages = ('multipath-tools', 'dlm-controld', 'gfs2-utils');
    
    # Foreach needed package, check if it is installed
    foreach my $pkg in (@needed_packages) {
        my $output = `dpkg -s $pkg 2>/dev/null`;
        if ($? != 0 or $output !~ /Status: install ok installed/) {
            push @missingPkgs, $pkg;
        }
    }

    return @missingPkgs;
}

# *********************************************************************
# Rescans for new SCSI devices on the system.
# Param:
#   boolNewArray (Default: 0): Where this should concider a new array 
#       that has never been attached to this host before
# Returns:
#   0 if successful scan, 1 if scan failed to finish or occur
# *********************************************************************
sub rescan_scsi_bus {
    my ($boolNewArray) = @_;
    # Setting boolNewArray value to default value if not provided
    $boolNewArray //= 0;
    
    my $cmdBase = "/usr/bin/rescan-scsi-bus.sh";
    my $multipath = " --multipath";
    my $largeLun = " --largelun";
    my $lipReset = " --issue-lip-wait=10";
    my $allTargets = " --alltargets";
    my $cmd = $cmdBase . $multipath . $largeLun;

    if ($boolNewArray) {
        my $cmd = $cmd . $lipReset . $allTargets;
    }
    
    print "Issuing command: $cmd";
    $result = system($cmd);

    return $result;
}

sub write_config_to_file {
    # Ensure the directory exists (optional safeguard)
    my $dir = dirname($config_location);
    if (!-d $dir) {
        die "Directory $dir does not exist!\n";
    }

    # Convert Perl structure to JSON
    my $json_text = to_json($hitachi_config, { pretty => 1, canonical => 1 });

    # Create a new IO::File object for writing
    my $fh = IO::File->new($config_location, '>')
        or die "Could not open $config_location for writing: $!";

    # Write JSON data
    print $fh $json_text;

    # Close filehandle
    $fh->close or warn "Could not close $config_location: $!";

    print "Wrote JSON configuration to $config_location\n";
}

# *********************************************************************
# Get the config data from the config file and returns its
# hash object. If config file is not found, it returns undef
# Returns:
#   Hash|undef: Server's Hitachi configuration including cluster
#               and multiapth information.
# *********************************************************************
sub read_config_from_file {
    my $fh = IO::File->new($config_location, '<')
        or return undef;

    my $json_text = do { local $/; <$fh> };
    $fh->close;

    return decode_json($json_text);
}

sub print_multipath_volumes {
    print "Multipath Volumes"
    foreach my $vol (@{$hitachi_config->{multipathVolumes}}) {
        print " - $vol->{friendlyName}\t(WWID: $vol->{wwid})\n";
    }
    print ""
}

sub get_hitachi_disks {
    my $cmd = "lsblk -ndo NAME,SIZE,WWN,MODEL | grep 'OPEN-V'";
    my $output = system($cmd)

    my @disks;

    foreach my $line (@output) {
        chomp $line;

        # Split by whitespace
        my ($device, $size, $wwid, $model) = split /\s+/, $line;

        # Store as a hash reference
        push @disks, {
            device => $device,
            size   => $size,
            wwid   => $wwid,
            model  => $model,
        };
    }

    return @disks;
}

sub convert_hitachi_disk_to_string {
    my($disk_ref) = @_;
    my %disk = %{$disk_ref};
    my $result = '';
    $result .= "$disk{device} . " " . $disk{size} . " " . $disk{wwid}";
    return $result
}

# *************************************************************************
# Gets the name of this PVE server
# Returns:
#   String: Name of this PVE server
# *************************************************************************
sub get_this_server_name {
    my $cmd = "hostname"
    return system($cmd)
}

# *************************************************************************
# Gets whether this node is part of a PVE cluster
# Returns:
#   Int: 1 (True) is it is part of a cluster, 0 (false) if it is not part 
#   of a cluster
# *************************************************************************
sub is_in_cluster {
    my $output = `pvecm status 2>&1`;  # capture stdout and stderr

    # Look for a line starting with "Name:"
    if ($output =~ /^Name:\s+(\S+)/m) {
        return 1;  # part of a cluster
    } else {
        return 0;  # not in a cluster
    }
}

# *************************************************************************
# Gets the list of node objects from the PVE cluster and returns the list of nodes
# as an array
# Returns:
#   Array(Hash): Nodes with attributes "Node"
# *************************************************************************
sub get_cluster_nodes {
    my @nodes;
    my $cmd = "pvecm nodes";
    my $result = system($cmd);
    my @lines = split /\n/, $result
    shift @lines; # Clearing blank line at top of output
    shift @lines; # Clearing out "Membership..."
    shift @lines; # Clearning out "-------"

    # Get Headers
    my $header_line = shift @lines;
    my @columns = split /\s+/, $header_line;

    for my $line (@lines) {
        next if $line =~ /^\s*$/;
        
        if ($line =~ /\s*(\d+)\s+\d+\s+(\S+)/) {
            my ($nodeId, $nodeName) = ($1, $2);
            $nodeName =~ s/\(local\)//;
            push @nodes, { nodeId => $nodeId, nodeName = $nodeName };
        }
    }

    return @nodes

    # for my $line (split /\n/, $text) {
    #     # Match lines that look like: "    1    1 pve1"
    #     if (%line =~ /^\s*\d+\s+\d+\s+(\S+)/) {
    #         my $name = $1;
    #         # Remove "(local)" if present
    #         $name =~ s/\(local\)//;
    #         # Trim trailing whitespace
    #         $name =~ s/\s+$//;
    #         push @names, $name
    #     }
    # }

    # return @names;
}

# **********************************************************
# Returns the name of the PVE Cluster this node is a part of
# Returns:
#   String: Name of the PVE Cluster
# **********************************************************
sub get_cluster_name {
    $cmd = "pvecm status";
    $output = system($cmd);
    my ($temp_cluster_name) = $output =~ /^Name:\s+(\S+)/m;
    if (defined $temp_cluster_name) {
        return $temp_cluster_name;
    } else {
        return undef;
    }
}

# **********************************************************************
# Loads the hitachi and multipathing config data from the config file.
# If the config file does not exist, a default config for this server
# is created and saved to the config_location
# **********************************************************************
sub load_data {
    %hitachi_config = read_config_from_file();

    if(!defined $hitachi_config) {
        %hitachi_config;
        
        $serverName = get_this_server_name();
        $mountRoot = "/mnt"
        $isClusterNode = is_in_cluster();
        if ($isClusterNode == 1) {
            $clusterName = get_cluster_name();
            @clusterNodes = get_cluster_nodes();
            $clusterNodeCount = scalar @clusterNodes;
        }
    }
}

# **********************************************************************
# Creates a GPT partition table and a primary partition on the given device.
# Then updates the system with the new partition using kpartx.
# Param:
#   String: The device on which to create the partition (e.g., /dev/sdx)
# Returns:
#   Integer: 0 (successful) or 1 (failed)
# **********************************************************************
sub make_gpt_partition {
    my ($device) = @_;
    my $partition = $device . "-part1";
    print "Creating GPT partition table and primary partition on $device...\n";
    $cmd = 'parted -s ' . $device . ' mklabel gpt mkpart primary "1 -1"';
    system($cmd);
    print "Updating system with partition on $partition...\n";
    $cmd = 'kpartx -a ' . $partition;
    my $status = system($cmd);
    return $status;
}