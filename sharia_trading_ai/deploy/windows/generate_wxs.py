#!/usr/bin/env python3
import os
import sys
import uuid
import re

def clean_id(s):
    # Wix IDs must only contain alphanumeric, underscores, or periods, and cannot start with a digit
    clean = re.sub(r'[^a-zA-Z0-9_\.]', '_', s)
    if clean[0].isdigit() or clean[0] == '.':
        clean = '_' + clean
    return clean[:70] # limit length just in case

def generate_wxs(source_dir, output_file):
    source_dir = os.path.abspath(source_dir)
    if not os.path.exists(source_dir):
        print(f"Error: Source directory {source_dir} does not exist.")
        sys.exit(1)

    print(f"Scanning directory: {source_dir}")

    # Build the directory tree
    dir_tree = {}
    file_map = {}

    for root, dirs, files in os.walk(source_dir):
        rel_path = os.path.relpath(root, source_dir)
        if rel_path == '.':
            current_node = dir_tree
        else:
            parts = rel_path.split(os.sep)
            node = dir_tree
            for part in parts:
                if part not in node:
                    node[part] = {}
                node = node[part]
            current_node = node

        # Save files
        file_map[rel_path] = files

    # Generate WiX XML
    xml_lines = []
    xml_lines.append('<?xml version="1.0" encoding="utf-8"?>')
    xml_lines.append('<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">')
    xml_lines.append('  <Product Id="*" Name="Sharia Trading AI" Language="1033" Version="1.0.0" Manufacturer="Sharia Trading Team" UpgradeCode="78fcd4b8-f1da-45e3-96b5-0c7f078d6b88">')
    xml_lines.append('    <Package InstallerVersion="200" Compressed="yes" InstallScope="perUser" />')
    xml_lines.append('    <MajorUpgrade DowngradeErrorMessage="A newer version of [ProductName] is already installed." />')
    xml_lines.append('    <MediaTemplate EmbedCab="yes" />')
    xml_lines.append('')
    xml_lines.append('    <Directory Id="TARGETDIR" Name="SourceDir">')
    xml_lines.append('      <Directory Id="LocalAppDataFolder">')
    xml_lines.append('        <Directory Id="INSTALLDIR" Name="Sharia Trading AI">')

    component_refs = []
    shortcuts = []

    def process_dir(node, rel_dir_path, indent):
        ind = ' ' * indent
        
        # Files in this directory
        files = file_map.get(rel_dir_path, [])
        for f in files:
            full_path = os.path.join(source_dir, rel_dir_path, f) if rel_dir_path != '.' else os.path.join(source_dir, f)
            src_rel_path = os.path.relpath(full_path, os.path.dirname(output_file))
            
            clean_name = clean_id(f)
            dir_suffix = clean_id(rel_dir_path) if rel_dir_path != '.' else 'root'
            comp_id = f"cmp_{clean_name}_{dir_suffix}"
            file_id = f"fil_{clean_name}_{dir_suffix}"
            
            xml_lines.append(f'{ind}  <Component Id="{comp_id}" Guid="*">')
            
            # Per-user installer MUST have a registry key under HKCU as keypath
            xml_lines.append(f'{ind}    <RegistryValue Root="HKCU" Key="Software\\ShariaTradingAI\\{comp_id}" Name="installed" Type="integer" Value="1" KeyPath="yes" />')
            
            # File tag
            # If the file is StartApp.vbs or StopApp.bat, we add shortcuts
            if f == "StartApp.vbs":
                xml_lines.append(f'{ind}    <File Id="{file_id}" Source="{src_rel_path}">')
                xml_lines.append(f'{ind}      <Shortcut Id="DesktopShortcut" Directory="DesktopFolder" Name="Sharia Trading AI" WorkingDirectory="INSTALLDIR" Advertise="no" />')
                xml_lines.append(f'{ind}      <Shortcut Id="StartMenuShortcut" Directory="ApplicationProgramsFolder" Name="Sharia Trading AI" WorkingDirectory="INSTALLDIR" Advertise="no" />')
                xml_lines.append(f'{ind}    </File>')
            elif f == "StopApp.bat":
                xml_lines.append(f'{ind}    <File Id="{file_id}" Source="{src_rel_path}">')
                xml_lines.append(f'{ind}      <Shortcut Id="StopShortcut" Directory="ApplicationProgramsFolder" Name="Hentikan Sharia Trading" WorkingDirectory="INSTALLDIR" Advertise="no" />')
                xml_lines.append(f'{ind}    </File>')
            else:
                xml_lines.append(f'{ind}    <File Id="{file_id}" Source="{src_rel_path}" />')
                
            xml_lines.append(f'{ind}  </Component>')
            component_refs.append(comp_id)

        # Subdirectories
        for subdir, subnode in node.items():
            clean_sub = clean_id(subdir)
            sub_rel_path = subdir if rel_dir_path == '.' else os.path.join(rel_dir_path, subdir)
            dir_id = f"dir_{clean_sub}_{clean_id(sub_rel_path)}"
            
            xml_lines.append(f'{ind}  <Directory Id="{dir_id}" Name="{subdir}">')
            process_dir(subnode, sub_rel_path, indent + 2)
            xml_lines.append(f'{ind}  </Directory>')

    # Start recursion from root node
    process_dir(dir_tree, '.', 8)

    xml_lines.append('        </Directory>')
    xml_lines.append('      </Directory>')
    xml_lines.append('      <Directory Id="DesktopFolder" Name="Desktop" />')
    xml_lines.append('      <Directory Id="ProgramMenuFolder">')
    xml_lines.append('        <Directory Id="ApplicationProgramsFolder" Name="Sharia Trading AI" />')
    xml_lines.append('      </Directory>')
    xml_lines.append('    </Directory>')
    xml_lines.append('')

    # Clean up shortcuts component
    xml_lines.append('    <DirectoryRef Id="ApplicationProgramsFolder">')
    xml_lines.append('      <Component Id="CleanupShortcuts" Guid="*">')
    xml_lines.append('        <RegistryValue Root="HKCU" Key="Software\\ShariaTradingAI\\Cleanup" Name="cleaned" Type="integer" Value="1" KeyPath="yes" />')
    xml_lines.append('        <RemoveFolder Id="CleanupProgramsFolder" On="uninstall" />')
    xml_lines.append('      </Component>')
    xml_lines.append('    </DirectoryRef>')
    component_refs.append("CleanupShortcuts")
    
    xml_lines.append('')
    xml_lines.append('    <Feature Id="ProductFeature" Title="Sharia Trading AI" Level="1">')
    xml_lines.append('      <ComponentGroupRef Id="ProductComponents" />')
    xml_lines.append('    </Feature>')
    xml_lines.append('')
    xml_lines.append('    <ComponentGroup Id="ProductComponents">')
    for ref in component_refs:
        xml_lines.append(f'      <ComponentRef Id="{ref}" />')
    xml_lines.append('    </ComponentGroup>')
    
    xml_lines.append('  </Product>')
    xml_lines.append('</Wix>')

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(xml_lines))

    print(f"Successfully generated {output_file} with {len(component_refs)} components.")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: generate_wxs.py <source_dir> <output_file>")
        sys.exit(1)
    generate_wxs(sys.argv[1], sys.argv[2])
