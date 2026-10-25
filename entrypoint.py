#!/usr/bin/env python3
import yaml, os, sys, hashlib, urllib.request, subprocess, jinja2, signal, shutil
from datetime import datetime
from pathlib import Path
import re

last_percent = None

class Logger:
    OKCYAN = '\033[96m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

    @staticmethod
    def info(message):
        print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " [" + Logger.OKCYAN + "INFO" + Logger.ENDC + "]" + " " + message)

    @staticmethod
    def warning(message):
        print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " [" + Logger.WARNING + "WARNING" + Logger.ENDC + "]" + " " + message)

    @staticmethod
    def error(message):
        print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " [" + Logger.FAIL + "ERROR" + Logger.ENDC + "]" + " " + message)

class ConfigError(Exception):
    pass

class Cleanup:
    nginx_started = False

    @staticmethod
    def run(signum, frame):
        if Cleanup.nginx_started:
            print("Stopping nginx.")
            subprocess.run(["nginx", "-s", "stop"], check=True)
        else:
            # Still preparing images. Unwind so that partial files are removed, then exit.
            print("Stopping before nginx was started.")
            raise SystemExit(128 + signum)

class Config:
    script_dir      = os.path.dirname(os.path.realpath(__file__))
    templates_dir   = "templates"
    mac_address     = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")

    @staticmethod
    def load(config_file_path):
        with open(config_file_path, 'r') as stream:
            try:
                #return yaml.safe_load(stream, Loader)
                return yaml.load(stream, Loader)
            except (yaml.YAMLError, OSError) as e:
                raise ConfigError(config_file_path + " could not be loaded:\n" + str(e))

    @staticmethod
    def validate(config):
        # Check config.yml before downloading images, and report all problems at once.
        # MAC addresses used as ids of autoinstalls are changed to lower case, because iPXE requests them in lower case.
        errors = []
        if not isinstance(config, dict):
            raise ConfigError("config.yml must be a mapping that has menus, autoinstalls and images")
        for section, section_type in (("menus", list), ("autoinstalls", list), ("images", dict)):
            if not isinstance(config.get(section), section_type):
                errors.append(section + " is missing or is not a " + ("list" if section_type == list else "mapping"))
        if errors:
            raise ConfigError(Config.format_errors(errors))

        for image_id, image in config["images"].items():
            if not isinstance(image, dict) or not isinstance(image.get("url"), str):
                errors.append("images." + str(image_id) + ": url is missing")

        for i, menu in enumerate(config["menus"]):
            if not isinstance(menu, dict):
                errors.append("menus[" + str(i) + "] is not a mapping")
            elif "image_id" in menu and menu["image_id"] not in config["images"]:
                errors.append("menus[" + str(i) + "] (id \"" + str(menu.get("id")) + "\"): image_id \"" + str(menu["image_id"]) + "\" is not in images")

        seen = {}
        for i, autoinstall in enumerate(config["autoinstalls"]):
            name = "autoinstalls[" + str(i) + "]"
            if not isinstance(autoinstall, dict):
                errors.append(name + " is not a mapping")
                continue
            autoinstall_id = autoinstall.get("id")
            if not isinstance(autoinstall_id, str):
                # YAML reads an unquoted MAC address that has only digits as a number (e.g. 52:54:00:30:00:00 -> 41135148000)
                errors.append(name + ": id " + str(autoinstall_id) + " is not a string. Quote MAC addresses in config.yml, like id: \"52:54:00:30:00:00\"")
                continue
            if Config.mac_address.match(autoinstall_id) and autoinstall_id != autoinstall_id.lower():
                Logger.warning(name + ": id \"" + autoinstall_id + "\" was changed to \"" + autoinstall_id.lower() + "\" because iPXE requests MAC addresses in lower case")
                autoinstall_id = autoinstall["id"] = autoinstall_id.lower()
            name += " (id \"" + autoinstall_id + "\")"
            if autoinstall_id in seen:
                errors.append(name + ": the same id is also used by autoinstalls[" + str(seen[autoinstall_id]) + "]")
            seen[autoinstall_id] = i
            template = autoinstall.get("template")
            if not isinstance(template, str):
                errors.append(name + ": template is missing")
            elif not os.path.isfile(os.path.join(Config.templates_dir, template)):
                errors.append(name + ": template \"" + template + "\" was not found in " + Config.templates_dir + "/")

        if errors:
            raise ConfigError(Config.format_errors(errors))

    @staticmethod
    def format_errors(errors):
        return "Configuration has " + str(len(errors)) + " error" + ("s" if len(errors) > 1 else "") + ":\n" + "\n".join("  - " + e for e in errors)

class Loader(yaml.SafeLoader):

    def __init__(self, stream):
        self._root = os.path.split(stream.name)[0]
        super(Loader, self).__init__(stream)

    def include(self, node):
        filename = os.path.join(self._root, self.construct_scalar(node))
        with open(filename, 'r') as f:
            #return yaml.safe_load(f, Loader)
            return yaml.load(f, Loader)

Loader.add_constructor('!include', Loader.include)

class Entrypoint:
    script_dir      = os.path.dirname(os.path.realpath(__file__))

    #image_dir       = os.path.join(script_dir, "os/images")
    #config_dir      = os.path.join(script_dir, "os/config")
    #autoinstall_dir = os.path.join(script_dir, "os/autoinstall")

    html_root_dir   = "/var/www"
    image_dir       = os.path.join(html_root_dir, "os/images")
    config_dir      = os.path.join(html_root_dir, "os/config")
    autoinstall_dir = os.path.join(html_root_dir, "os/autoinstall")

    download_dirs   = [image_dir, config_dir, autoinstall_dir]

    jinja2_env      = jinja2.Environment(loader=jinja2.FileSystemLoader("."))

    def __init__(self, config):
        signal.signal(signal.SIGTERM, Cleanup.run)
        self.config = config
        self.jinja2_env.filters['pretty']           = Filter.pretty
        self.jinja2_env.filters['basename']         = Filter.basename
        self.jinja2_env.filters['regex_replace']    = Filter.regex_replace

    def deploy(self):
        # Create directories
        for download_dir in self.download_dirs:
            os.makedirs(download_dir, exist_ok=True)

        # Generate autoinstall script(cloud-init) and boot.ipxe before downloading OS images.
        # They do not depend on the images, and errors in templates are reported without waiting for downloads.
        errors = []
        for i, autoinstall in enumerate(self.config["autoinstalls"]):
            try:
                self.generate_autoinstall_script(autoinstall)
            except Exception as e:
                errors.append("autoinstalls[" + str(i) + "] (id \"" + autoinstall["id"] + "\"): failed to render template \""
                              + autoinstall["template"] + "\": " + Entrypoint.describe(e))
        try:
            self.generate_boot_ipxe()
        except Exception as e:
            errors.append("boot.ipxe.j2: failed to render: " + Entrypoint.describe(e))
        if errors:
            raise ConfigError(Config.format_errors(errors))

        # Download OS images
        for image_key, image_info in self.config["images"].items():
            downloaded_image_path = os.path.join(self.image_dir, os.path.basename(image_info["url"]))
            extracted_image_path = os.path.join(self.image_dir, image_key, "casper")

            Downloader.download(image_info["url"], downloaded_image_path, (image_info["sha256"] if "sha256" in image_info else None))
            Extractor.extract(downloaded_image_path, "/casper", os.path.join(self.image_dir, image_key, "casper"))

        self.run_nginx()

    @staticmethod
    def describe(e):
        message = type(e).__name__ + ": " + str(e)
        if getattr(e, "lineno", None):
            message += " (line " + str(e.lineno) + ")"
        return message

    def generate_autoinstall_script(self, autoinstall):
        template = self.jinja2_env.get_template("templates/" + autoinstall["template"])

        if "args" in autoinstall:
            rendered = template.render(config=self.config, args=autoinstall["args"])
        else:
            rendered = template.render(config=self.config)

        # Make directory if it does not exist
        autoinstall_dir = os.path.join(self.autoinstall_dir, autoinstall["id"])

        if not os.path.exists(autoinstall_dir):
            os.makedirs(autoinstall_dir)

        with open(os.path.join(autoinstall_dir, "user-data"), 'w') as f:
            f.write(rendered)

        # An explanation of meta-data
        # https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_and_managing_cloud-init_for_rhel_8/configuring-cloud-init_cloud-content
        Path(os.path.join(autoinstall_dir, "meta-data")).touch()
        # cloud-init also requests vendor-data and retries many times if it does not exist. An empty file means no vendor data.
        Path(os.path.join(autoinstall_dir, "vendor-data")).touch()

    def generate_boot_ipxe(self):
        template = self.jinja2_env.get_template("boot.ipxe.j2")
        rendered = template.render(config=self.config)

        with open(os.path.join(self.config_dir, "boot.ipxe"), 'w') as f:
            f.write(rendered)

    def run_nginx(self):
        Logger.info("Starting nginx(nginx -g daemon off;)")
        Cleanup.nginx_started = True
        subprocess.run(["nginx", "-g", "daemon off;"], check=True)

class Filter:
    @staticmethod
    def pretty(d, indent=0, result=""):
        for key, value in d.items():
            result += " " * indent + str(key)
            if isinstance(value, dict):
                result = Filter.pretty(value, indent=(indent + 2), result=result + ":\n")
            else:
                result += ": " + str(value) + "\n"
        return result

    @staticmethod
    def basename(path):
        return os.path.basename(path)

    @staticmethod
    def regex_replace(s, pattern, replace):
        return re.sub(pattern, replace, s)

class Extractor:
    @staticmethod
    def extract(image_path, extract_src_path, extract_dest_path):
        Logger.info("Extracting an image " + image_path + " from \"" + extract_src_path + "\" to \"" + extract_dest_path + "\"")
        #print("Extracting an image" + image_path + " from \"" + extract_src_path + "\" to \"" + extract_dest_path + "\"")
        #subprocess.run(["osirrox", "-indev", ./os/images/ubuntu-22.04.3-live-server-amd64.iso ], check=True)
        rendered = subprocess.run(["osirrox", "-indev", image_path, "-extract", extract_src_path, extract_dest_path], check=True)

class Downloader:

    @staticmethod
    def show_progress(downloaded, total_size):
        global last_percent
        if total_size <= 0:
            # The server did not send Content-Length
            return

        downloaded = min(downloaded, total_size)
        percent = downloaded * 100 // total_size
        # Print the progress every 10 percent so that it is also readable in "docker logs"
        if last_percent is None or percent // 10 > last_percent // 10:
            print("  " + str(percent) + "% (" + str(downloaded) + "/" + str(total_size) + " bytes)")
            last_percent = percent

    # Seconds to wait for each read from the server before giving up
    timeout = 60

    @staticmethod
    def download(url, download_path, sha256):
        file_name = os.path.basename(url)
        if sha256 != None:
            # YAML reads an unquoted sha256 that has only digits as a number and drops its leading zeros
            if not isinstance(sha256, str):
                raise ValueError("sha256 of " + file_name + " in config.yml must be quoted, like sha256: \"<value>\"")
            sha256 = sha256.lower()
        if Downloader.check_if_image_exists(download_path, sha256):
            print("Image " + file_name + "(" + url + ") has already exists, skipping download it")
            return

        print("Downloading " + file_name + "(" + url + ")")

        # Download to a temporary file and rename it when it is complete,
        # so that a file with the final name is never a partial download.
        part_path = download_path + ".part"
        try:
            Downloader.fetch(url, part_path)
            if sha256 != None and Downloader.sha256sum(part_path) != sha256:
                raise RuntimeError("sha256 of " + file_name + " does not match " + sha256)
            os.replace(part_path, download_path)
        except BaseException as e:
            if isinstance(e, (SystemExit, KeyboardInterrupt)):
                print("Download of " + file_name + " was cancelled")
            else:
                print("Failed to download " + file_name + ": " + (str(e) or type(e).__name__))
            if os.path.exists(part_path):
                os.remove(part_path)
            raise

    @staticmethod
    def fetch(url, download_path):
        global last_percent
        last_percent = None
        with urllib.request.urlopen(url, timeout=Downloader.timeout) as response, open(download_path, 'wb') as f:
            total_size = int(response.headers.get("Content-Length", -1))
            downloaded = 0
            Downloader.show_progress(downloaded, total_size)
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                f.write(chunk)
                downloaded += len(chunk)
                Downloader.show_progress(downloaded, total_size)

        if total_size >= 0 and downloaded < total_size:
            raise urllib.error.ContentTooShortError(
                "retrieval incomplete: got only " + str(downloaded) + " out of " + str(total_size) + " bytes", None)

    @staticmethod
    def sha256sum(path):
        # Read the image in chunks so that a large ISO is not loaded into memory at once
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def check_if_image_exists(download_path, sha256):
        if os.path.isfile(download_path):
            if sha256 != None:
                return Downloader.sha256sum(download_path) == sha256
            return True

        return False

class PrepareCustomResources:
    @staticmethod
    def exec():
        # Copy custom files /etc/ipxe-image-server/{config.yml,boot.ipxe.j2}
        # to /config.yml, /boot.ipxe.j2 if they were existed.
        if os.path.isfile("/etc/ipxe-image-server/config.yml"):
            Logger.info("Copy custom file /etc/ipxe-image-server/config.yml to /config.yml")
            shutil.copy("/etc/ipxe-image-server/config.yml", "/config.yml")
        if os.path.isfile("/etc/ipxe-image-server/boot.ipxe.j2"):
            Logger.info("Copy custom file /etc/ipxe-image-server/boot.ipxe.j2 to /boot.ipxe.j2")
            shutil.copy("/etc/ipxe-image-server/boot.ipxe.j2", "/boot.ipxe.j2")
        if os.path.exists("/etc/ipxe-image-server/templates/"):
            if os.path.exists("/templates"):
                shutil.rmtree("/templates")
            Logger.info("Copy custom templates /etc/ipxe-image-server/templates to /templates")
            shutil.copytree("/etc/ipxe-image-server/templates", "/templates")

if __name__ == '__main__':
    os.chdir('/')
    PrepareCustomResources.exec()
    try:
        config = Config.load("./config.yml")
        Config.validate(config)
        Entrypoint(config).deploy()
    except ConfigError as e:
        Logger.error(str(e))
        sys.exit(1)

