#!/usr/bin/env python

import argparse
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
import zipfile

pack_format_map = {
    '1.6': 1,
    '1.7': 1,
    '1.8': 1,
    '1.9': 2,
    '1.10': 2,
    '1.11': 3,
    '1.12': 3,
    '1.13': 4,
    '1.14': 4,
    '1.15': 5,
    '1.15': 5,
    '1.16': 5,
    '1.16.2': 6,
    '1.16.5': 6,
    '1.17': 7,
    '1.17.1': 7,
    '1.18': 8,
    '1.19': 9,
}

color_codes = {
    'dark_red': '§4',
    'red': '§c',
    'gold': '§6',
    'yellow': '§e',
    'dark_green': '§2',
    'green': '§a',
    'aqua': '§b',
    'dark_aqua': '§3',
    'dark_blue': '§1',
    'blue': '§9',
    'light_purple': '§d',
    'dark_purple': '§5',
    'white': '§f',
    'gray': '§7',
    'dark_gray': '§8',
    'black': '§0',
    'reset': '§r',
    'bold': '§l',
    'italic': '§o',
    'underline': '§n',
    'strike': '§m',
    'zalgo': '§k',
}

def download(url, sha1=None, as_json=False, as_utf8=False):
    content = None
    cache_path = None
    if sha1 is not None:
        # Try to load cached version.
        cache_path = os.path.join('cache', sha1)
        try:
            with open(cache_path, 'rb') as f:
                content = f.read()
        except FileNotFoundError:
            pass
    if content is None:
        # Fall back to download.
        print('Downloading asset %s...' % url)
        with urllib.request.urlopen(url) as response:
            content = response.read()
        # Save new downloaded content
        if cache_path is not None:
            with open(cache_path, 'wb') as f:
                f.write(content)
    if as_json:
        content = json.loads(content)
    elif as_utf8:
        content = content.decode('utf8')
    return content


def download_languages(*versions):
    # Download the master manifest.
    print('Downloading master version manifest...')
    master_manifest = download('https://launchermeta.mojang.com/mc/game/version_manifest.json', as_json=True)
    # For each of the versions...
    version_languages = []
    for version in versions:
        languages = []
        # Find the version manifest in the master manifest.
        print('[%s] Finding version in master manifest...' % version)
        version_manifest_url = None
        for entry in master_manifest['versions']:
            if entry['id'] == version:
                version_manifest_url = entry['url']
                break
        else:
            raise ValueError('Version not found in manifest: %s' % version)
        # Download the version manifest.
        print('[%s] Downloading version manifest...' % version)
        version_manifest = download(version_manifest_url, as_json=True)
        # Get the jar and grab language assets from there.
        client_jar = download(version_manifest['downloads']['client']['url'], version_manifest['downloads']['client']['sha1'])
        client = zipfile.ZipFile(io.BytesIO(client_jar), 'r')
        for path in client.namelist():
            if path.startswith('assets/minecraft/lang'):
                print('Found lang asset in JAR: %s' % path)
                key = path[len('assets/'):]
                language_content = client.read(path).decode('utf8')
                languages.append((key, language_content))
        # Download loose files from the asset index.
        asset_index = download(version_manifest['assetIndex']['url'], version_manifest['assetIndex']['sha1'], as_json=True)
        for key, value in asset_index['objects'].items():
            if key.startswith('minecraft/lang/'):
                # Download the language file.
                print('[%s] Retrieving language %s' % (version, key))
                language_content = download('http://resources.download.minecraft.net/%s/%s' % (value['hash'][:2], value['hash']), value['hash'], as_utf8=True)
                languages.append((key, language_content))
        version_languages.append((version, languages))
    print('Languages downloaded.')
    return version_languages


def load_language(contents, pack_format):
    # New packs: JSON.
    if pack_format >= 4:
        return json.loads(contents)
    # Old packs: key-value format.
    lines = contents.rstrip().replace('\r', '').split('\n')
    lines = list(filter(bool, lines))
    return {key: value for key, value in [line.partition('=')[::2] for line in lines]}


def dump_language(translation, pack_format):
    # New packs: JSON.
    if pack_format >= 4:
        return json.dumps(translation, indent=2)
    # Old packs: key-value format.
    return ''.join(['%s=%s\n' % (key, translation[key]) for key in sorted(translation.keys())])


def generate_pack(version, languages, colors):
    print('Generating pack for version %s...'  % version)
    # Guess correct pack format.
    for key, value in pack_format_map.items():
        if version.startswith(key):
            pack_format = value
    print('Using pack format %d for version %s.' % (pack_format, version))
    # Create zipfile.
    f = zipfile.ZipFile(os.path.join('output', 'ColoredSubtitles-%s.zip' % version), 'w', compression=zipfile.ZIP_DEFLATED)
    # Insert metadata.
    metadata = {
        'pack': {
            'pack_format': pack_format,
            'description': 'By Kosmolot',
        }
    }
    f.writestr('pack.mcmeta', json.dumps(metadata))
    # Insert pack artwork.
    #f.write('pack.png') # TODO
    # Keep track of the unhandled ones.
    unhandled = set()
    # Map and write language files.
    for language_path, language_content in languages:
        # Load translation file.
        translation = load_language(language_content, pack_format)

        # Map translation file.
        for key in list(translation.keys()):
            new_color = None
            # Color rules are applied consecutively, last one wins.
            for prefix, color in colors:
                if key.startswith(prefix):
                    new_color = color
            # Apply formatting codes if needed.
            if new_color is not None:
                translation[key] = color_codes[new_color] + translation[key]
            else:
                if key.startswith('subtitles.'):
                    unhandled.add(key)
        # Create new mapped file.
        f.writestr(os.path.join('assets', language_path), dump_language(translation, pack_format))
    for key in sorted(unhandled):
        print("Warning: no color code found for", key)
    print('Generated pack for version %s.'  % version)

        
def main():
    # Create directories.
    for directory in ['cache', 'output']:
        os.makedirs(directory, exist_ok=True)
    # Find out what the user wants.
    parser = argparse.ArgumentParser(description='Build Colored Subtitles resource pack.')
    parser.add_argument('-c', '--color', action='append', default=[], type=lambda s: s.partition('=')[0::2])
    parser.add_argument('-v', '--version', action='append', default=[], required=True)
    args = parser.parse_args()
    # Merge default color mappings with user-requested mappings.
    with open('default_colors.json', 'rb') as f:
        color_mappings = json.load(f)
    color_mappings.extend(args.color)
    # Download language files for each requested version.
    version_languages = download_languages(*args.version)
    # Generate packs.
    for version, languages in version_languages:
        generate_pack(version, languages, color_mappings)


if __name__ == '__main__':
    main()
