#!/usr/bin/env python3
import yaml, os, hashlib, urllib.request, progressbar, subprocess, jinja2, signal
from datetime import datetime
from pathlib import Path
import re

pbar = None

class Logger:
    OKCYAN = '\033[96m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

    @staticmethod
    def info(message):
        print(datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " [" + Logger.OKCYAN + "INFO" + Logger.ENDC + "]" + " " + message)

class Cleanup:
    @staticmethod
    def run():
        print("Stopping nginx.")
        subprocess.run(["nginx", "-s", "stop"], check=True)

class Config:
    script_dir      = os.path.dirname(os.path.realpath(__file__))

    @staticmethod
    def load(config_file_path):
        with open(config_file_path, 'r') as stream:
            try:
                return yaml.safe_load(stream)
            except yaml.YAMLError as e:
                print(e)
                raise e

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

        # Download OS images
        for image_key, image_info in self.config["images"].items():
            downloaded_image_path = os.path.join(self.image_dir, os.path.basename(image_info["url"]))
            extracted_image_path = os.path.join(self.image_dir, image_key, "casper")

            Downloader.download(image_info["url"], downloaded_image_path, (image_info["sha256"] if "sha256" in image_info else None))
            Extractor.extract(downloaded_image_path, "/casper", os.path.join(self.image_dir, image_key, "casper"))

        # Generate autoinstall script(cloud-init)
        for autoinstall in self.config["autoinstalls"]:
            self.generate_autoinstall_script(autoinstall)

        self.generate_boot_ipxe()
        self.run_nginx()

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

    def generate_boot_ipxe(self):
        template = self.jinja2_env.get_template("boot.ipxe.j2")
        rendered = template.render(config=self.config)

        with open(os.path.join(self.config_dir, "boot.ipxe"), 'w') as f:
            f.write(rendered)

    def run_nginx(self):
        Logger.info("Starting nginx(nginx -g daemon off;)")
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
    def show_progress(block_num, block_size, total_size):
        # https://stackoverflow.com/a/46825841
        global pbar
        if pbar is None:
            pbar = progressbar.ProgressBar(maxval=total_size)
            pbar.start()

        downloaded = block_num * block_size
        if downloaded < total_size:
            pbar.update(downloaded)
        else:
            pbar.finish()
            pbar = None

    @staticmethod
    def download(url, download_path, sha256):
        file_name = os.path.basename(url)
        if Downloader.check_if_image_exists(download_path, sha256):
            print("Image " + file_name + "(" + url + ") has already exists, skipping download it")
            return

        print("Downloading " + file_name + "(" + url + ")")

        try:
            urllib.request.urlretrieve(url, download_path, Downloader.show_progress)
        except urllib.error.URLError as e:
            print(e)
            # Remove the file if it is not downloaded completely
            os.remove(download_path)
            raise e
        except KeyboardInterrupt as e:
            print("Download cancelled")
            os.remove(download_path)
            raise e

    @staticmethod
    def check_if_image_exists(download_path, sha256):
        if os.path.isfile(download_path):
            if sha256 != None:
                return hashlib.sha256(open(download_path, 'rb').read()).hexdigest() == sha256
            return True

        return False

if __name__ == '__main__':
    os.chdir('/')
    Entrypoint(Config.load("./config.yml")).deploy()

