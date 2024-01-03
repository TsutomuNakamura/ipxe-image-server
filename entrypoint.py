#!/usr/bin/env python3
import yaml, os, hashlib, urllib.request, progressbar

pbar = None

class Config:
    @staticmethod
    def load(config_file_path):
        with open(config_file_path, 'r') as stream:
            try:
                return yaml.safe_load(stream)
            except yaml.YAMLError as e:
                print(exc)
                raise e

class Deployment:
    script_dir      = os.path.dirname(os.path.realpath(__file__))

    image_dir       = os.path.join(script_dir, "os/images")
    config_dir      = os.path.join(script_dir, "os/config")
    autoinstall_dir = os.path.join(script_dir, "os/autoinstall")

    download_dirs   = [image_dir, config_dir, autoinstall_dir]

    def __init__(self, config):
        self.config = config

    def deploy(self):
        # Create directories
        for download_dir in self.download_dirs:
            os.makedirs(download_dir, exist_ok=True)

        # Download OS images
        for k, image_info in self.config["images"].items():
            Downloader.download(image_info["url"], self.image_dir, (image_info["sha256"] if "sha256" in image_info else None))

        # Create boot menu entries
        for entry in self.config["menu"]:

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
    def download(url, download_dir, sha256):
        file_name = os.path.basename(url)
        download_path = os.path.join(download_dir, file_name)
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
    Deployment(Config().load("./config.yml")).deploy()

