#!/usr/bin/env python3
import yaml, os, sys, hashlib, urllib.request, subprocess, jinja2, signal, shutil, json, tempfile
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
    # Defaults of the user that the built-in templates create. The password is "p@ssw0rd".
    # It is public, so password login over SSH must not be enabled with it.
    default_username = "me"
    default_password = "$6$xyz$rfUoxhnScmjOykLAVIhgfxmKgIWmTirRSrIZ9j5EJ1Vf765rQS.dCbXjXBx4PuhbcNNrXx2XpwUywQ96C7EJB/"

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
                continue
            if "extract" in image:
                files = image["extract"]
                if (not isinstance(files, list) or not files
                        or not all(isinstance(f, str) and f.strip("/") and ".." not in f.split("/") for f in files)):
                    errors.append("images." + str(image_id) + ": extract must be a list of paths in the image, like [\"casper/vmlinuz\", \"casper/initrd\"]")
                else:
                    image["extract"] = [f.strip("/") for f in files]

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
        self.jinja2_env.filters['to_yaml']          = Filter.to_yaml
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
            name = "autoinstalls[" + str(i) + "] (id \"" + autoinstall["id"] + "\")"
            try:
                rendered = self.generate_autoinstall_script(autoinstall)
            except Exception as e:
                errors.append(name + ": failed to render template \"" + autoinstall["template"] + "\": " + Entrypoint.describe(e))
                continue
            errors += Entrypoint.check_user_data(name, rendered)
        try:
            self.generate_boot_ipxe()
        except Exception as e:
            errors.append("boot.ipxe.j2: failed to render: " + Entrypoint.describe(e))
        if errors:
            raise ConfigError(Config.format_errors(errors))

        # Download OS images
        for image_key, image_info in self.config["images"].items():
            downloaded_image_path = os.path.join(self.image_dir, os.path.basename(image_info["url"]))

            Downloader.download(image_info["url"], downloaded_image_path, (image_info["sha256"] if "sha256" in image_info else None))
            Extractor.extract(image_key, downloaded_image_path, image_info.get("extract", Extractor.default_files),
                              os.path.join(self.image_dir, image_key))

        self.run_nginx()

    @staticmethod
    def check_user_data(name, rendered):
        # Check the user-data that the installer will get, so that this also works for custom templates.
        # Returns a list of errors, and prints warnings.
        try:
            user_data = yaml.safe_load(rendered)
        except yaml.YAMLError as e:
            detail = getattr(e, "problem", None) or str(e).replace("\n", " ")
            if getattr(e, "problem_mark", None):
                detail += " (line " + str(e.problem_mark.line + 1) + ")"
            return [name + ": the rendered user-data is not valid YAML: " + detail]
        autoinstall = user_data.get("autoinstall") if isinstance(user_data, dict) else None
        if not isinstance(autoinstall, dict):
            return []
        identity = autoinstall.get("identity") if isinstance(autoinstall.get("identity"), dict) else {}
        ssh = autoinstall.get("ssh") if isinstance(autoinstall.get("ssh"), dict) else {}
        if not ssh.get("install-server"):
            return []
        keys = ssh.get("authorized-keys") or []
        # Subiquity enables password login over SSH by default when there is no authorized key
        allow_pw = ssh.get("allow-pw", not keys)
        if allow_pw and identity.get("password") == Config.default_password:
            return [name + ": password login over SSH is enabled with the built-in default password \"p@ssw0rd\". "
                    + "Set your own password hash (e.g. \"openssl passwd -6\"), add authorized-keys, or set allow-pw to false"]
        if not keys and not allow_pw:
            Logger.warning(name + ": no one can log in over SSH, because there are no authorized-keys and allow-pw is false")
        return []

    @staticmethod
    def describe(e):
        message = type(e).__name__ + ": " + str(e)
        if getattr(e, "lineno", None):
            message += " (line " + str(e.lineno) + ")"
        return message

    def generate_autoinstall_script(self, autoinstall):
        template = self.jinja2_env.get_template("templates/" + autoinstall["template"])

        rendered = template.render(config=self.config, args=(autoinstall.get("args") or {}),
                                   default_username=Config.default_username, default_password=Config.default_password)

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
        return rendered

    def generate_boot_ipxe(self):
        template = self.jinja2_env.get_template("boot.ipxe.j2")
        rendered = template.render(config=self.config)

        with open(os.path.join(self.config_dir, "boot.ipxe"), 'w') as f:
            f.write(rendered)

    def run_nginx(self):
        Logger.info("Starting nginx(nginx -g daemon off;)")
        Cleanup.nginx_started = True
        subprocess.run(["nginx", "-g", "daemon off;"], check=True)

class IndentedSequenceDumper(yaml.SafeDumper):
    # Indent items of a list under their key, like the other examples in this project
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)

class Filter:
    @staticmethod
    def to_yaml(value, indent=0):
        # Write a value as YAML that is read back as the same value. Unlike pretty, this quotes strings when needed,
        # e.g. a MAC address of only digits, or a string that contains ": " or " #".
        text = yaml.dump(value, Dumper=IndentedSequenceDumper, default_flow_style=False, sort_keys=False,
                         allow_unicode=True, width=float("inf"))
        if not isinstance(value, (dict, list)):
            # A scalar is written in the line of its key
            return text.removesuffix("\n...\n").rstrip("\n")
        return "\n".join(" " * indent + line for line in text.rstrip("\n").split("\n"))

    @staticmethod
    def pretty(d, indent=0, result=""):
        # Deprecated: it does not quote values. Use to_yaml instead. This is kept for existing custom templates.
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
    # Files that boot.ipxe.j2 loads. The installer gets everything else from the ISO itself (url=...iso).
    default_files   = ["casper/vmlinuz", "casper/initrd"]
    # Records which image and files were extracted, so that they are not extracted again at every start
    stamp_name      = ".extracted"

    @staticmethod
    def extract(image_key, image_path, files, dest_dir):
        image_stat = os.stat(image_path)
        stamp = json.dumps({"image": os.path.basename(image_path), "size": image_stat.st_size,
                            "mtime": image_stat.st_mtime_ns, "files": files}, sort_keys=True)
        stamp_path = os.path.join(dest_dir, Extractor.stamp_name)
        if all(os.path.isfile(os.path.join(dest_dir, f)) for f in files) and Extractor.read(stamp_path) == stamp:
            Logger.info("Files of " + image_key + " have already been extracted, skipping extracting them")
        else:
            Extractor.extract_files(image_key, image_path, files, dest_dir)
            with open(stamp_path, 'w') as f:
                f.write(stamp)
        Extractor.report_unused_files(files, dest_dir)

    @staticmethod
    def extract_files(image_key, image_path, files, dest_dir):
        Logger.info("Extracting " + ", ".join(files) + " from " + image_path + " to " + dest_dir)
        os.makedirs(dest_dir, exist_ok=True)
        # Extract to a temporary directory and move the files when all of them are extracted,
        # so that an interrupted extraction never leaves partial files.
        temp_dir = tempfile.mkdtemp(prefix=".extracting-", dir=dest_dir)
        try:
            command = ["osirrox", "-indev", image_path]
            for f in files:
                command += ["-extract", "/" + f, os.path.join(temp_dir, f)]
            if subprocess.run(command).returncode != 0:
                raise ConfigError("images." + image_key + ": could not extract " + ", ".join(files) + " from " + image_path
                                  + ". Check images." + image_key + ".extract in config.yml, and that the image is not broken")
            for f in files:
                extracted_path = os.path.join(temp_dir, f)
                # Files in ISO images are read-only
                os.chmod(extracted_path, 0o644)
                os.makedirs(os.path.dirname(os.path.join(dest_dir, f)), exist_ok=True)
                os.replace(extracted_path, os.path.join(dest_dir, f))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def report_unused_files(files, dest_dir):
        # Older versions extracted the whole /casper. Tell how much space those files use, but do not delete them.
        used = {os.path.normpath(os.path.join(dest_dir, f)) for f in files}
        unused_size = 0
        unused_dirs = set()
        for d in {os.path.dirname(os.path.join(dest_dir, f)) for f in files}:
            for root, dirs, names in os.walk(d):
                for name in names:
                    path = os.path.normpath(os.path.join(root, name))
                    if path not in used and name != Extractor.stamp_name:
                        unused_size += os.path.getsize(path)
                        unused_dirs.add(os.path.relpath(root, Entrypoint.image_dir))
        if unused_size:
            size = (str(round(unused_size / 1024 ** 3, 1)) + " GiB") if unused_size >= 1024 ** 3 else (str(round(unused_size / 1024 ** 2, 1)) + " MiB")
            Logger.warning(size + " of files in " + ", ".join(sorted(unused_dirs))
                           + " (under the images directory) are not used. They were extracted by an older version. "
                           + "Refer to \"Removing files extracted by older versions\" in README.md to remove them")

    @staticmethod
    def read(path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return None

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

