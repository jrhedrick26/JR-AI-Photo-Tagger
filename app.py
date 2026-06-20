import os
import sys
import json
import time
import shutil
import subprocess
import io
from datetime import datetime
import google.generativeai as genai
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QTextEdit, QLabel, 
                             QProgressBar, QMessageBox, QLineEdit, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QDialog, QStyle, 
                             QSplitter, QComboBox, QFormLayout, QSpinBox, QDialogButtonBox, QCheckBox)
from PyQt6.QtGui import QIcon, QPixmap, QImage
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PIL import Image
import numpy as np
import keyring
from keyring.errors import KeyringError

# Disable Pillow's size limit to safely process massive panoramas
Image.MAX_IMAGE_PIXELS = None

import exiftool

try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False


# Constants for secure credential storage
KEYRING_SERVICE_NAME = "JR-AI-Photo-Tagger"
KEYRING_API_KEY_USER = "gemini_api_key"

def get_app_data_dir():
    """Creates and returns a safe, writable directory in the user's Documents folder."""
    home = os.path.expanduser("~")
    app_dir = os.path.join(home, "Documents", "JR AI Photo Tagger")
    if not os.path.exists(app_dir):
        try:
            os.makedirs(app_dir)
        except Exception:
            app_dir = os.getcwd() 
    return app_dir

APP_DIR = get_app_data_dir()
CONFIG_FILE_PATH = os.path.join(APP_DIR, "config.json")
LOGS_DIR = os.path.join(APP_DIR, "logs")

def find_exiftool_executable():
    """Locate ExifTool executable safely for standalone macOS and Windows environments."""
    # 1. Check system path
    path = shutil.which("exiftool")
    if path:
        return path
    
    # 2. Check explicitly next to the standalone Windows executable
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        win_path = os.path.join(exe_dir, "exiftool.exe")
        if os.path.exists(win_path):
            return win_path

    # 3. Check standard macOS paths
    standard_mac_paths = [
        "/opt/homebrew/bin/exiftool",
        "/usr/local/bin/exiftool"
    ]
    for p in standard_mac_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
            
    return "exiftool" 


def extract_embedded_preview(file_path):
    """Attempt to extract embedded JPEG preview from RAW metadata using ExifTool."""
    exiftool_path = find_exiftool_executable()
    if not exiftool_path or exiftool_path == "exiftool":
        exiftool_path = shutil.which("exiftool")
        if not exiftool_path:
            return None
            
    preview_tags = ["-PreviewImage", "-JpgFromRaw", "-ThumbnailImage"]
    for tag in preview_tags:
        try:
            res = subprocess.run(
                [exiftool_path, "-b", tag, file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if res.returncode == 0 and len(res.stdout) > 100:
                return res.stdout
        except Exception:
            pass
    return None


def load_preview_image(file_path):
    """Intelligently load images, handling macOS Permission constraints."""
    try:
        raw_extensions = ['.arw', '.cr2', '.nef', '.dng', '.raf', '.orf']
        if any(file_path.lower().endswith(ext) for ext in raw_extensions):
            # Try embedded preview extraction first (50x faster)
            preview_bytes = extract_embedded_preview(file_path)
            if preview_bytes:
                try:
                    return Image.open(io.BytesIO(preview_bytes))
                except Exception as e:
                    print(f"Failed to open extracted preview for {file_path}: {e}")

            # Fallback to rawpy
            if RAWPY_AVAILABLE:
                try:
                    with rawpy.imread(file_path) as raw:
                        rgb = raw.postprocess(use_camera_wb=True, half_size=True)
                    return Image.fromarray(rgb)
                except Exception as e:
                    print(f"rawpy failed on {file_path}, falling back to standard loader. Error: {e}")
            else:
                print(f"rawpy is not installed or available, falling back to standard loader for {file_path}")
        
        return Image.open(file_path)
    except PermissionError:
        raise PermissionError(f"macOS blocked access to {file_path}. Please grant Folder Access in System Settings.")


class ImagePreviewWorker(QThread):
    preview_ready_signal = pyqtSignal(QImage, str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.is_cancelled = False

    def run(self):
        try:
            img = load_preview_image(self.file_path)
            img.thumbnail((1200, 1200))
            img = img.convert("RGBA")
            data = img.tobytes("raw", "RGBA")
            # Create a deep copy of QImage to avoid memory garbage collection issues in PyQt6
            qim = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy()
            
            if not self.is_cancelled:
                self.preview_ready_signal.emit(qim, self.file_path)
                
            if hasattr(img, 'close'):
                img.close()
        except Exception as e:
            print(f"Preview error: {e}")
            if not self.is_cancelled:
                self.preview_ready_signal.emit(QImage(), self.file_path)


class FolderScanWorker(QThread):
    progress_signal = pyqtSignal(str)
    files_ready_signal = pyqtSignal(list)
    
    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path
        self.is_cancelled = False
    
    def run(self):
        valid_extensions = ('.arw', '.cr2', '.nef', '.dng', '.tiff', '.tif', '.jpg', '.jpeg')
        new_files = []
        
        try:
            for root, dirs, files in os.walk(self.folder_path):
                if self.is_cancelled:
                    break
                
                for file in files:
                    if self.is_cancelled:
                        break
                    
                    if file.lower().endswith(valid_extensions):
                        new_files.append(os.path.join(root, file))
                        self.progress_signal.emit(f"Found {len(new_files)} photos...")
            
            self.files_ready_signal.emit(new_files)
        except Exception as e:
            self.progress_signal.emit(f"Error scanning folder: {str(e)}")
            self.files_ready_signal.emit([])


class SettingsDialog(QDialog):
    """A dialog window for configuring AI limits and Data Safety."""
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Generation Settings")
        self.setMinimumWidth(350)
        
        self.settings = current_settings.copy()
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.title_spin = QSpinBox()
        self.title_spin.setRange(2, 20)
        self.title_spin.setValue(self.settings.get("title_max_words", 7))
        
        self.caption_spin = QSpinBox()
        self.caption_spin.setRange(5, 50)
        self.caption_spin.setValue(self.settings.get("caption_max_words", 15))
        
        self.keyword_spin = QSpinBox()
        self.keyword_spin.setRange(3, 50)
        self.keyword_spin.setValue(self.settings.get("keyword_max_count", 25))
        
        self.backup_check = QCheckBox("Keep Original File Backups (Recommended)")
        self.backup_check.setChecked(self.settings.get("backup_originals", True))
        
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems([
            "gemini-3.5-flash",
            "gemini-3.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-pro"
        ])
        current_model = self.settings.get("gemini_model", "gemini-3.5-flash")
        idx = self.model_combo.findText(current_model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.model_combo.setCurrentText(current_model)

        form_layout.addRow("Max Title Words:", self.title_spin)
        form_layout.addRow("Max Caption Words:", self.caption_spin)
        form_layout.addRow("Max Keywords:", self.keyword_spin)
        form_layout.addRow("Gemini Model:", self.model_combo)
        form_layout.addRow("", self.backup_check)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_settings(self):
        return {
            "title_max_words": self.title_spin.value(),
            "caption_max_words": self.caption_spin.value(),
            "keyword_max_count": self.keyword_spin.value(),
            "backup_originals": self.backup_check.isChecked(),
            "gemini_model": self.model_combo.currentText().strip()
        }


class AIAnalysisWorker(QThread):
    progress_signal = pyqtSignal(int, int)
    log_signal = pyqtSignal(str)
    result_ready_signal = pyqtSignal(str, dict)
    finished_signal = pyqtSignal(str)

    def __init__(self, file_paths, api_key, batch_context, photo_style, settings):
        super().__init__()
        self.file_paths = file_paths
        self.api_key = api_key
        self.batch_context = batch_context
        self.photo_style = photo_style
        self.settings = settings
        self.is_cancelled = False

    def get_image_context(self, et, file_path):
        try:
            meta = et.get_metadata(file_path, params=["-n"])[0]
            date_str = meta.get("EXIF:DateTimeOriginal", "an unknown date/time")
            lat = meta.get("EXIF:GPSLatitude") or meta.get("Composite:GPSLatitude")
            lon = meta.get("EXIF:GPSLongitude") or meta.get("Composite:GPSLongitude")
            gps_context = f"Coordinates: {lat}, {lon}" if lat and lon else "Unknown location"
            return gps_context, date_str
        except Exception:
            return "Unknown location", "Unknown date"

    def run(self):
        try:
            genai.configure(api_key=self.api_key)
            model_name = self.settings.get("gemini_model", "gemini-3.5-flash")
            model = genai.GenerativeModel(model_name)
        except Exception as e:
            error_msg = str(e)
            self.log_signal.emit(f"✕ API Configuration Error: {error_msg}")
            self.log_signal.emit("💡 Verify your API key at: https://ai.google.dev/")
            self.log_signal.emit("💡 Common issues: Invalid key, expired key, or no free credits remaining")
            self.finished_signal.emit("Configuration failed.")
            return

        style_guides = {
            "Standard": "a standard visual layout",
            "Real Estate & Architecture": "an architectural perspective. Focus explicitly on structural features, spatial layout, building materials, and interior/exterior lighting techniques",
            "Portrait & Wedding": "a portrait/event style. Focus explicitly on human emotion, connection, posing, wardrobe, and subject isolation/depth of field",
            "Fine Art Landscape": "a fine art landscape style. Focus explicitly on natural elements, geographical mood, tonal range, weather, and dramatic lighting",
            "Drone / Aerial": "an aerial/drone perspective. Focus explicitly on geographical scale, bird's-eye patterns, leading lines from above, and topography",
            "Street Photography": "a street photography style. Focus explicitly on candid moments, the human condition, urban juxtaposition, shadows, and daily life context",
            "Travel & Adventure": "a travel and adventure style. Focus explicitly on cultural essence, sense of place, journey, local landmarks, and environmental storytelling"
        }
        active_style_guide = style_guides.get(self.photo_style, style_guides["Standard"])

        t_max = self.settings.get("title_max_words", 7)
        c_max = self.settings.get("caption_max_words", 15)
        k_max = self.settings.get("keyword_max_count", 25)

        total_files = len(self.file_paths)
        
        try:
            with exiftool.ExifToolHelper(executable=find_exiftool_executable()) as et:
                for index, file_path in enumerate(self.file_paths):
                    if self.is_cancelled:
                        self.log_signal.emit("🛑 AI Generation cancelled by user.")
                        break

                    if not os.path.exists(file_path):
                        continue
                    
                    base_name = os.path.basename(file_path)
                    self.log_signal.emit(f"Analyzing visual assets for: {base_name}...")

                    # 1. Attempt loading image locally (skip this file if file is corrupted/unreadable)
                    try:
                        gps_ctx, time_ctx = self.get_image_context(et, file_path)
                        img = load_preview_image(file_path)
                        img.thumbnail((1024, 1024))
                        rgb_img = img.convert("RGB")
                    except PermissionError as pe:
                        self.log_signal.emit(f"✕ Permission Denied: macOS blocked access to {base_name}. Go to System Settings -> Privacy & Security -> Files and Folders.")
                        continue
                    except Exception as e:
                        self.log_signal.emit(f"✕ Skipping file error on {base_name} (loading/processing): {str(e)}\n")
                        continue

                    # 2. Run API generation with retry and fatal error check
                    try:
                        user_context_injection = ""
                        if self.batch_context:
                            user_context_injection = f"CRITICAL USER CONTEXT NOTES: Use this exact context/event/client info to guide details: '{self.batch_context}'\n"

                        prompt = f"""
                        You are an expert photography archivist creating standard Lightroom metadata. I am providing an image taken on {time_ctx} at {gps_ctx}.
                        {user_context_injection}
                        Read any visible text or branding on buildings or subjects. If coordinates are provided, use them for geographical context.
                        
                        Return a JSON object with EXACTLY these three keys: 'title', 'caption', 'keywords'.
                        
                        1. 'title': A punchy, highly accurate, production-ready title (maximum {t_max} words). Focus entirely on the primary subject, the specific angle, and the mood/lighting (e.g., 'Golden Hour', 'Night', 'Neon'). NEVER include the date or time format (e.g., 2024, 11-21) in the title. Do NOT waste words starting the title with "Aerial View of" or "Overhead of"—put those descriptors in the keywords instead. To avoid repetitive titles in a batch, focus on the UNIQUE visual composition of the image (e.g., 'Symmetrical Skyline', 'Close-Up', 'Framed by Trees').
                        
                        2. 'caption': A straightforward, factual catalog sentence (maximum {c_max} words) analyzed through the lens of {active_style_guide}. Describe exactly what the subject is, the setting, and the lighting. IF landmarks are visible, explicitly name the 1 or 2 most prominent ones. CRITICAL: Vary your sentence structures. Do NOT begin every caption with "An aerial view..." or "The...". NEVER include the EXIF date in the text. This MUST be a single, grammatically correct, and flowing sentence without semicolons or lists.
                        
                        3. 'keywords': An array of up to {k_max} highly specific tags. Inject stylistic elements for {active_style_guide}, alongside artistic terms, accurate lighting, location, and core subjects. DO NOT use generic terms like 'picture', 'image', 'photo', or 'daytime'. DO NOT mash words together into camelCase or hashtags. Always use natural spaces between words in a single tag (e.g., use 'North Carolina' instead of 'NorthCarolina'). Ensure all Keywords are formatted in Title Case.
                        """
                        
                        success = False
                        for attempt in range(3):
                            if self.is_cancelled:
                                break
                            try:
                                response = model.generate_content(
                                    [prompt, rgb_img],
                                    generation_config={"response_mime_type": "application/json"}
                                )
                                success = True
                                break
                            except Exception as api_e:
                                err_msg = str(api_e).lower()
                                if "429" in err_msg or "quota" in err_msg or "exhausted" in err_msg:
                                    self.log_signal.emit(f"⚠️ API Rate Limit hit. Throttling for 15 seconds to recover...")
                                    for _ in range(15):
                                        if self.is_cancelled:
                                            break
                                        time.sleep(1)
                                elif "network" in err_msg or "connect" in err_msg or "unavailable" in err_msg:
                                    self.log_signal.emit(f"⚠️ Network connection issue. Retrying in 10 seconds...")
                                    for _ in range(10):
                                        if self.is_cancelled:
                                            break
                                        time.sleep(1)
                                else:
                                    raise api_e

                        if self.is_cancelled:
                            if hasattr(img, 'close'): img.close()
                            break

                        if not success:
                            raise Exception("Failed after maximum network retries.")

                        # Safety cleaner for markdown formatting
                        raw_json_str = response.text.strip().removeprefix('```json').removesuffix('```').strip()
                        metadata = json.loads(raw_json_str)
                        
                        kw_list = metadata.get("keywords", [])
                        if isinstance(kw_list, str):
                            kw_list = [k.strip() for k in kw_list.split(",") if k.strip()]
                        
                        cleaned_metadata = {
                            "title": metadata.get("title", "").strip(),
                            "caption": metadata.get("caption", "").strip(),
                            "keywords": ", ".join([str(k).strip() for k in kw_list if str(k).strip()])
                        }

                        if hasattr(img, 'close'):
                            img.close()

                        self.result_ready_signal.emit(file_path, cleaned_metadata)
                        self.log_signal.emit(f"✓ AI analysis received for {base_name}")
                        
                        for _ in range(3): # Standard Rate Limiter sleep
                            if self.is_cancelled:
                                break
                            time.sleep(1)

                    except Exception as api_error:
                        if hasattr(img, 'close'):
                            img.close()
                        self.log_signal.emit(f"✕ Fatal API error during analysis: {str(api_error)}")
                        self.log_signal.emit("🛑 Aborting the batch processing due to fatal API error.")
                        break

                    self.progress_signal.emit(index + 1, total_files)

        except Exception as global_e:
            self.log_signal.emit(f"⚠️ Critical ExifTool Error: {global_e}")

        status_msg = "Process Cancelled!" if self.is_cancelled else "AI Stage Completed! Review your grid entries."
        self.finished_signal.emit(status_msg)



class FileWriteWorker(QThread):
    progress_signal = pyqtSignal(int, int)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)

    def __init__(self, run_data, creator, copyright_text, batch_context, photo_style, settings):
        super().__init__()
        self.run_data = run_data
        self.creator = creator
        self.copyright_text = copyright_text
        self.batch_context = batch_context
        self.photo_style = photo_style
        self.settings = settings
        self.is_cancelled = False

    def run(self):
        start_time = time.time()
        total_files = len(self.run_data)
        success_count = 0
        
        if not os.path.exists(LOGS_DIR):
            try:
                os.makedirs(LOGS_DIR)
            except Exception as e:
                self.log_signal.emit(f"⚠️ Warning: Could not create logs directory: {e}")
        
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_filename = os.path.join(LOGS_DIR, f"Batch_Log_{timestamp}.txt")
        
        log_content = f"--- JR AI PHOTO TAGGER : BATCH RUN LOG ---\n"
        log_content += f"Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        log_content += f"Creator: {self.creator} | Copyright: {self.copyright_text}\n"
        log_content += f"AI Style Applied: {self.photo_style}\n"
        log_content += f"AI Limits: Title ({self.settings.get('title_max_words')}w) | Caption ({self.settings.get('caption_max_words')}w) | Keywords ({self.settings.get('keyword_max_count')})\n"
        log_content += f"Batch Notes: {self.batch_context}\n"
        log_content += "="*60 + "\n\n"
        
        # Check overwrite settings
        use_overwrite = not self.settings.get("backup_originals", True)
        params = ["-overwrite_original"] if use_overwrite else []

        try:
            with exiftool.ExifToolHelper(executable=find_exiftool_executable()) as et:
                for index, (file_path, title, caption, kw_str) in enumerate(self.run_data):
                    if self.is_cancelled:
                        self.log_signal.emit("🛑 Commit cancelled by user.")
                        break

                    base_name = os.path.basename(file_path)
                    try:
                        keywords = [k.strip() for k in kw_str.split(",") if k.strip()]

                        tags = {
                            "XMP-dc:Title": title,
                            "XMP-dc:Description": caption,
                            "XMP-dc:Subject": keywords,
                        }
                        
                        if self.creator:
                            tags["XMP-dc:Creator"] = self.creator
                        if self.copyright_text:
                            tags["XMP-dc:Rights"] = self.copyright_text

                        et.set_tags([file_path], tags=tags, params=params)
                        success_count += 1
                        self.log_signal.emit(f"💾 Permanently written: {base_name}")
                        
                        log_content += f"File: {base_name}\nTitle: {title}\nCaption: {caption}\nKeywords: {kw_str}\n"
                        log_content += "-"*60 + "\n"
                        
                    except PermissionError:
                        self.log_signal.emit(f"✕ Permission Denied on {base_name}: macOS blocked access. Check Privacy & Security.")
                        log_content += f"File: {base_name} -> PERMISSION DENIED\n"
                        log_content += "-"*60 + "\n"
                    except Exception as e:
                        self.log_signal.emit(f"✕ Save failed on {base_name}: {str(e)}")
                        log_content += f"File: {base_name} -> FAILED TO WRITE: {str(e)}\n"
                        log_content += "-"*60 + "\n"

                    self.progress_signal.emit(index + 1, total_files)
                    
        except Exception as global_e:
            self.log_signal.emit(f"⚠️ Critical Engine Error: ExifTool encountered a system problem. {global_e}")
            log_content += f"\nCRITICAL ERROR: {global_e}\n"

        end_time = time.time()
        duration = end_time - start_time
        mins, secs = divmod(int(duration), 60)
        
        log_content += "\n" + "="*60 + "\n"
        log_content += f"BATCH AUDIT SUMMARY\n"
        log_content += f"Total Files Processed: {total_files}\n"
        log_content += f"Successful Writes: {success_count}\n"
        log_content += f"Failed Writes: {total_files - success_count}\n"
        log_content += f"Total Write Duration: {mins}m {secs}s\n"
        log_content += "="*60 + "\n"

        try:
            with open(log_filename, "w", encoding="utf-8") as f:
                f.write(log_content)
        except Exception as e:
            self.log_signal.emit(f"⚠️ Failed to save plain text log: {str(e)}")

        status_msg = (
            f"Process Cancelled. Saved {success_count} files before stopping.\nCheck your Documents folder for logs." 
            if self.is_cancelled else 
            f"Successfully saved metadata directly inside {success_count} of {total_files} file(s)!\n"
            f"A detailed audit log has been saved to your Documents folder.\n\n"
            "🚨 CRITICAL LIGHTROOM REQUIREMENT:\n"
            "1. Open Adobe Lightroom Classic.\n"
            "2. Highlight these processed photos.\n"
            "3. In the top menu bar, select: Metadata -> Read Metadata from File."
        )
        self.finished_signal.emit(status_msg)


class APITestWorker(QThread):
    result_signal = pyqtSignal(bool, str)

    def __init__(self, api_key, model_name):
        super().__init__()
        self.api_key = api_key
        self.model_name = model_name

    def run(self):
        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            # Run a tiny prompt to verify key & model presence
            response = model.generate_content("Ping", generation_config={"max_output_tokens": 5})
            
            # If we reached this line without throwing an exception, the credentials and model name are valid
            self.result_signal.emit(True, f"Connection Successful!\n\nYour API key is valid and '{self.model_name}' is online and active.")
        except Exception as e:
            err_msg = str(e)
            err_lower = err_msg.lower()
            
            if "api key" in err_lower or "api_key" in err_lower or "400" in err_lower:
                friendly_msg = "Connection Failed: Invalid API Key.\n\nPlease double check that you have pasted your key correctly and that it doesn't contain any trailing spaces."
            elif "not found" in err_lower or "404" in err_lower or "not available" in err_lower or "no longer available" in err_lower:
                friendly_msg = f"Connection Failed: Model Not Available.\n\nThe model '{self.model_name}' is not available or has been deprecated. Please open Settings and select a recommended model."
            elif "quota" in err_lower or "limit" in err_lower or "exhausted" in err_lower or "429" in err_lower:
                friendly_msg = "Connection Failed: Quota/Rate Limit Exhausted.\n\nYour Gemini API quota has been exceeded or your billing details are inactive. Check your Google AI Studio billing dashboard."
            elif "network" in err_lower or "connect" in err_lower or "unreachable" in err_lower or "unavailable" in err_lower:
                friendly_msg = "Connection Failed: Network Error.\n\nCould not reach Google servers. Please check your internet connection and try again."
            else:
                friendly_msg = f"Connection Failed:\n\n{err_msg}"
                
            self.result_signal.emit(False, friendly_msg)


class PhotoMetadataApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_files = []
        self.grid_data_map = {}
        self.start_time = None
        self.current_preview_pixmap = None
        self.preview_worker = None
        self.folder_scan_worker = None
        
        self.app_settings = {
            "title_max_words": 7, 
            "caption_max_words": 15,
            "keyword_max_count": 25,
            "backup_originals": True,
            "gemini_model": "gemini-3.5-flash"
        }
        
        self.init_ui()
        self.load_config()
        self.exiftool_available = self.check_exiftool()

    def check_exiftool(self):
        try:
            with exiftool.ExifToolHelper(executable=find_exiftool_executable()) as et:
                return True
        except Exception:
            QMessageBox.critical(self, "Missing Dependency: ExifTool", 
                                 "ExifTool is not installed or cannot be found!\n\n"
                                 "This app requires ExifTool to save metadata safely.\n"
                                 "Please download the MacOS Package from exiftool.org and restart the app.")
            self.file_label.setText("⚠️ ExifTool not found. Please install ExifTool to tag photos.")
            self.btn_add_files.setEnabled(False)
            self.btn_add_folder.setEnabled(False)
            return False

    def init_ui(self):
        self.setWindowTitle("JR AI Photo Tagger")
        self.resize(1300, 850)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.setAcceptDrops(True)

        main_layout = QHBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # --- LEFT PANEL: Controls & Grid ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # Row 1: API, Settings & Help
        row1 = QHBoxLayout()
        self.api_input = QLineEdit()
        self.api_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_input.setPlaceholderText("Gemini API Key...")
        self.btn_test_api = QPushButton("⚡ Test")
        self.btn_test_api.clicked.connect(self.test_api_connection)

        row1.addWidget(QLabel("API Key:"))
        row1.addWidget(self.api_input, 2)
        row1.addWidget(self.btn_test_api)
        
        self.btn_settings = QPushButton("⚙️ Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        row1.addWidget(self.btn_settings)
        
        self.btn_help = QPushButton("❓ Help Guide")
        self.btn_help.clicked.connect(self.show_help_guide)
        row1.addWidget(self.btn_help)
        left_layout.addLayout(row1)

        # Row 2: Creator & Copyright
        row2 = QHBoxLayout()
        self.creator_input = QLineEdit()
        self.creator_input.setPlaceholderText("e.g. JR Photography")
        self.copyright_input = QLineEdit()
        self.copyright_input.setPlaceholderText("e.g. © 2026 JR")
        row2.addWidget(QLabel("Creator:"))
        row2.addWidget(self.creator_input)
        row2.addWidget(QLabel("Copyright:"))
        row2.addWidget(self.copyright_input)
        left_layout.addLayout(row2)

        # Row 3: AI Style Dropdown & Batch Context
        row3 = QHBoxLayout()
        self.style_dropdown = QComboBox()
        self.style_dropdown.addItems([
            "Standard", 
            "Real Estate & Architecture", 
            "Portrait & Wedding", 
            "Fine Art Landscape", 
            "Drone / Aerial", 
            "Street Photography", 
            "Travel & Adventure"
        ])
        self.context_input = QLineEdit()
        self.context_input.setPlaceholderText("Optional: Project name, Client, Event...")
        row3.addWidget(QLabel("AI Style:"))
        row3.addWidget(self.style_dropdown)
        row3.addWidget(QLabel("Batch Notes:"))
        row3.addWidget(self.context_input, 2)
        left_layout.addLayout(row3)

        self.file_label = QLabel("No files selected. Add ARW, DNG, or TIFF files to begin.")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.file_label)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.btn_add_files = QPushButton("+ Add Files")
        self.btn_add_files.clicked.connect(self.add_files)
        btn_layout.addWidget(self.btn_add_files)

        self.btn_add_folder = QPushButton("+ Add Folder")
        self.btn_add_folder.clicked.connect(self.add_folder)
        btn_layout.addWidget(self.btn_add_folder)

        self.btn_run_ai = QPushButton("Generate AI")
        self.btn_run_ai.clicked.connect(self.run_ai_analysis)
        self.btn_run_ai.setEnabled(False)
        btn_layout.addWidget(self.btn_run_ai)

        self.btn_commit = QPushButton("Commit Changes")
        self.btn_commit.clicked.connect(self.commit_grid_to_files)
        self.btn_commit.setEnabled(False)
        self.btn_commit.setStyleSheet("font-weight: bold;")
        btn_layout.addWidget(self.btn_commit)
        
        self.btn_cancel = QPushButton("🛑 Stop / Cancel")
        self.btn_cancel.clicked.connect(self.cancel_processing)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setStyleSheet("color: #d9534f; font-weight: bold;")
        btn_layout.addWidget(self.btn_cancel)
        
        self.btn_reset = QPushButton("🗑️ Clear Queue")
        self.btn_reset.clicked.connect(self.reset_workspace)
        self.btn_reset.setStyleSheet("color: #d9534f;")
        btn_layout.addWidget(self.btn_reset)
        
        left_layout.addLayout(btn_layout)

        # Spreadsheet Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["File Name", "Title", "Caption", "Keywords"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.update_image_preview)
        left_layout.addWidget(self.table)

        # Status Layout
        status_layout = QHBoxLayout()
        self.eta_label = QLabel("ETA: --")
        self.cost_label = QLabel("Estimated API Cost: --")
        status_layout.addWidget(self.eta_label)
        status_layout.addStretch()
        status_layout.addWidget(self.cost_label)
        left_layout.addLayout(status_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setFormat("%p% (%v/%m Files)") 
        left_layout.addWidget(self.progress_bar)
        
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(80)
        left_layout.addWidget(self.log_output)

        self.splitter.addWidget(left_panel)

        # --- RIGHT PANEL: Live Visual Preview & Metadata ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.preview_label = QLabel("Select a row to preview image")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #1e1e1e; color: #888888; border-radius: 5px;")
        self.preview_label.setSizePolicy(self.preview_label.sizePolicy().Policy.Expanding, self.preview_label.sizePolicy().Policy.Expanding)
        self.preview_label.setMinimumWidth(350)
        right_layout.addWidget(self.preview_label, stretch=3)
        
        self.preview_metadata = QTextEdit()
        self.preview_metadata.setReadOnly(True)
        self.preview_metadata.setStyleSheet("background-color: #2b2b2b; color: #e0e0e0; border-radius: 5px; padding: 10px; font-size: 13px;")
        self.preview_metadata.setHtml("<b>Image Metadata:</b><br><br><i>Select an image to view details...</i>")
        right_layout.addWidget(self.preview_metadata, stretch=1)
        
        self.splitter.addWidget(right_panel)
        self.splitter.setSizes([800, 500])

    def load_config(self):
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                with open(CONFIG_FILE_PATH, "r") as f:
                    data = json.load(f)
                    # Load non-sensitive config
                    self.creator_input.setText(data.get("creator", ""))
                    self.copyright_input.setText(data.get("copyright", ""))
                    self.app_settings["title_max_words"] = data.get("title_max_words", 7)
                    self.app_settings["caption_max_words"] = data.get("caption_max_words", 15)
                    self.app_settings["keyword_max_count"] = data.get("keyword_max_count", 25)
                    self.app_settings["backup_originals"] = data.get("backup_originals", True)
                    self.app_settings["gemini_model"] = data.get("gemini_model", "gemini-3.5-flash")
            except Exception:
                pass
        
        # Load API key from secure storage
        try:
            api_key = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_API_KEY_USER)
            if api_key:
                self.api_input.setText(api_key)
        except KeyringError:
            # Keyring unavailable on this system, user will need to enter manually
            pass

    def save_config(self):
        config_data = {
            "creator": self.creator_input.text().strip(),
            "copyright": self.copyright_input.text().strip(),
            "title_max_words": self.app_settings["title_max_words"],
            "caption_max_words": self.app_settings["caption_max_words"],
            "keyword_max_count": self.app_settings["keyword_max_count"],
            "backup_originals": self.app_settings["backup_originals"],
            "gemini_model": self.app_settings["gemini_model"]
        }
        try:
            with open(CONFIG_FILE_PATH, "w") as f:
                json.dump(config_data, f)
        except Exception:
            pass
        
        # Save API key to secure storage (not in config file)
        api_key = self.api_input.text().strip()
        if api_key:
            try:
                keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_API_KEY_USER, api_key)
            except KeyringError:
                # Keyring unavailable; API key will need to be re-entered next time
                pass

    def open_settings(self):
        dialog = SettingsDialog(self.app_settings, self)
        if dialog.exec():
            self.app_settings = dialog.get_settings()
            self.save_config()

    def update_image_preview(self):
        selected_items = self.table.selectedItems()
        if not selected_items:
            return
            
        row = selected_items[0].row()
        file_item = self.table.item(row, 0)
        
        title = self.table.item(row, 1).text() if self.table.item(row, 1) else ""
        caption = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
        keywords = self.table.item(row, 3).text() if self.table.item(row, 3) else ""
        
        meta_html = (
            f"<h3 style='margin-bottom:2px; color:#5bc0de;'>{title}</h3>"
            f"<p style='margin-top:2px;'><b>Caption:</b> {caption}</p>"
            f"<p><b>Keywords:</b> <i>{keywords}</i></p>"
        )
        self.preview_metadata.setHtml(meta_html)
        
        if file_item:
            file_path = file_item.toolTip()
            self.preview_label.setText("Loading High-Res Preview...")
            
            if self.preview_worker is not None:
                self.preview_worker.is_cancelled = True
                
            self.preview_worker = ImagePreviewWorker(file_path)
            self.preview_worker.preview_ready_signal.connect(self.display_preview_image)
            self.preview_worker.start()

    def display_preview_image(self, qim, file_path):
        if qim.isNull():
            self.preview_label.setText("Preview unavailable for this file format. Ensure macOS has granted Folder permissions.")
            self.current_preview_pixmap = None
            return
            
        self.current_preview_pixmap = QPixmap.fromImage(qim)
        self.scale_and_set_preview()

    def scale_and_set_preview(self):
        if self.current_preview_pixmap is not None:
            scaled_pixmap = self.current_preview_pixmap.scaled(
                self.preview_label.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scale_and_set_preview()

    def show_help_guide(self):
        help_text = (
            "<h3>📋 JR AI Photo Tagger Manual</h3><hr>"
            "<b>1. Setup & Configuration:</b> Enter your Gemini API key, Creator name, and Copyright details. Your API key is securely stored on your computer using your system's credential manager, so you only need to enter it once.<br><br>"
            "<b>2. Getting Your API Key:</b> Visit <a href='https://ai.google.dev/'>https://ai.google.dev/</a> to create a free Gemini API key. New users typically get $300 in monthly free credits.<br><br>"
            "<b>3. Adjusting AI Directives:</b> Click <b>⚙️ Settings</b> to establish word limits for titles and captions, and configure file backup protocols. Use the <b>AI Style</b> dropdown to change the semantic analysis approach for your specific photography genre.<br><br>"
            "<b>4. The Power of 'Batch Notes':</b> The AI only reads pixels and EXIF metadata (date, location, camera model). It cannot know client names or project details. Use the <b>Batch Notes</b> field to supply off-camera context like 'Corporate annual gala 2026' or 'Sunset beach engagement shoot'.<br><br>"
            "<b>5. Compiling the Queue:</b> Build batches dynamically using <b>+ Add Files</b> and <b>+ Add Folder</b>. You can repeatedly add multiple folders to create deep processing pipelines. The app calculates estimated API costs in real-time based on image count.<br><br>"
            "<b>6. Live Auditing & Correction:</b> Run the AI engine by clicking <b>Generate AI</b>. Select any row in the results table to preview the image on the right and read the generated metadata instantly. You can manually edit titles, captions, and keywords directly in the table cells before committing.<br><br>"
            "<b>7. Writing & Audit Logs:</b> Click <b>Commit Changes</b> to have ExifTool embed data directly into your original image files. Every commit run automatically creates a comprehensive transaction log saved to ~/Documents/JR AI Photo Tagger/logs/ with timestamps, file names, and write status.<br><br>"
            "<b>8. Lightroom Syncing:</b> After committing, open Adobe Lightroom Classic, select your processed photos, and go to <b>Metadata → Read Metadata from File</b> to sync the newly written metadata into Lightroom's database. Your photos are now permanently archived with professional metadata.<br><br>"
            "<b>9. Backup & Safety:</b> By default, the app keeps original file backups (_original files) before writing metadata. You can disable this in Settings if disk space is limited, but backups are recommended for first-time users.<br><br>"
            "<b>10. Troubleshooting:</b> If you see 'API Rate Limit' warnings, the app automatically throttles requests. For permission errors, grant your app access in System Settings → Privacy & Security → Files and Folders."
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Workspace Documentation")
        dialog_layout = QVBoxLayout()
        text_widget = QTextEdit()
        text_widget.setHtml(help_text)
        text_widget.setReadOnly(True)
        text_widget.setMinimumSize(600, 650)
        dialog_layout.addWidget(text_widget)
        dialog.setLayout(dialog_layout)
        dialog.exec()

    def check_unsaved_changes(self):
        if self.btn_commit.isEnabled():
            reply = QMessageBox.question(self, 'Unsaved Changes', 
                                         'You have uncommitted AI suggestions. Adding new photos will reset the grid so you can start a new combined batch. Continue?',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.force_clear_workspace()
                return True
            else:
                return False
        return True

    def force_clear_workspace(self):
        self.selected_files = []
        self.grid_data_map.clear()
        self.table.setRowCount(0)
        self.file_label.setText("No files selected. Add ARW, DNG, or TIFF files to begin.")
        self.btn_run_ai.setEnabled(False)
        self.btn_commit.setEnabled(False)
        self.btn_cancel.setVisible(False)
        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.eta_label.setText("ETA: --")
        self.cost_label.setText("Estimated API Cost: --")
        self.preview_label.setText("Select a row to preview image")
        self.preview_label.setPixmap(QPixmap())
        self.current_preview_pixmap = None
        self.preview_metadata.setHtml("<b>Image Metadata:</b><br><br><i>Select an image to view details...</i>")

    def reset_workspace(self):
        if not self.check_unsaved_changes():
            return
        self.force_clear_workspace()

    def cancel_processing(self):
        if hasattr(self, 'ai_worker') and self.ai_worker and self.ai_worker.isRunning():
            self.ai_worker.is_cancelled = True
            self.log_output.append("🛑 Cancelling AI Generation... waiting for current photo to finish.")
        if hasattr(self, 'file_worker') and self.file_worker and self.file_worker.isRunning():
            self.file_worker.is_cancelled = True
            self.log_output.append("🛑 Cancelling Commit... waiting for current photo to finish.")
        if self.folder_scan_worker and self.folder_scan_worker.isRunning():
            self.folder_scan_worker.is_cancelled = True

    def append_to_queue(self, new_files):
        if len(new_files) > 200:
            reply = QMessageBox.question(self, 'Large Batch Warning', 
                                         f'You are about to add {len(new_files)} files to the queue. Processing a massive batch might take a long time. Are you sure you want to proceed?',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        added_count = 0
        for file_path in new_files:
            if file_path not in self.grid_data_map:
                self.selected_files.append(file_path)
                row_idx = self.table.rowCount()
                self.table.insertRow(row_idx)
                
                file_item = QTableWidgetItem(os.path.basename(file_path))
                file_item.setFlags(file_item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                file_item.setToolTip(file_path)
                
                self.table.setItem(row_idx, 0, file_item)
                self.table.setItem(row_idx, 1, QTableWidgetItem("Pending AI..."))
                self.table.setItem(row_idx, 2, QTableWidgetItem("Pending AI..."))
                self.table.setItem(row_idx, 3, QTableWidgetItem("Pending AI..."))
                
                self.grid_data_map[file_path] = row_idx
                added_count += 1
                
        if added_count > 0:
            self.file_label.setText(f"Loaded {len(self.selected_files)} file(s). Ready for processing.")
            self.btn_run_ai.setEnabled(True)
            self.preview_metadata.setHtml("<b>Image Metadata:</b><br><br><i>Select an image to view details...</i>")
            
            num_files = len(self.selected_files)
            estimated_cost = num_files * 0.00005 
            if estimated_cost < 0.01:
                self.cost_label.setText("Estimated API Cost: < $0.01 (Free Tier Eligible)")
            else:
                self.cost_label.setText(f"Estimated API Cost: ~${estimated_cost:.2f}")

    def add_files(self):
        if not self.check_unsaved_changes():
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Photos", "", "Photos (*.arw *.cr2 *.nef *.dng *.tiff *.tif *.jpg *.jpeg)"
        )
        if files:
            self.append_to_queue(files)

    def on_folder_scan_progress(self, status_msg):
        self.file_label.setText(status_msg)
    
    def on_folder_scan_complete(self, new_files):
        if new_files:
            self.append_to_queue(new_files)
        else:
            QMessageBox.information(self, "No Photos Found", "No supported photo files were found in that folder.")
        self.folder_scan_worker = None

    def add_folder(self):
        if not self.check_unsaved_changes():
            return
            
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            # Show progress dialog while scanning
            self.file_label.setText("🔍 Scanning folder for photos...")
            
            # Run folder scan in background thread
            self.folder_scan_worker = FolderScanWorker(folder)
            self.folder_scan_worker.progress_signal.connect(self.on_folder_scan_progress)
            self.folder_scan_worker.files_ready_signal.connect(self.on_folder_scan_complete)
            self.folder_scan_worker.start()

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        
        if self.start_time and current > 0:
            elapsed = time.time() - self.start_time
            avg_time = elapsed / current
            remaining_files = total - current
            eta_sec = int(avg_time * remaining_files)
            mins, secs = divmod(eta_sec, 60)
            
            if remaining_files > 0:
                self.eta_label.setText(f"ETA: {mins}m {secs}s")
            else:
                self.eta_label.setText("ETA: Complete")

    def run_ai_analysis(self):
        api_key = self.api_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Missing API Key", "Please paste your Gemini API key.\n\nGet a free key at: https://ai.google.dev/")
            return

        self.save_config()
        self.start_time = time.time()

        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_run_ai.setEnabled(False)
        self.btn_commit.setEnabled(False)
        self.btn_reset.setEnabled(False)
        self.btn_cancel.setVisible(True)
        
        style = self.style_dropdown.currentText()
        context = self.context_input.text().strip()
        
        self.ai_worker = AIAnalysisWorker(self.selected_files, api_key, context, style, self.app_settings)
        self.ai_worker.progress_signal.connect(self.update_progress)
        self.ai_worker.log_signal.connect(self.log_output.append)
        self.ai_worker.result_ready_signal.connect(self.update_grid_row)
        self.ai_worker.finished_signal.connect(self.ai_analysis_finished)
        self.ai_worker.start()

    def update_grid_row(self, file_path, data):
        row_idx = self.grid_data_map.get(file_path)
        if row_idx is not None:
            self.table.setItem(row_idx, 1, QTableWidgetItem(data["title"]))
            self.table.setItem(row_idx, 2, QTableWidgetItem(data["caption"]))
            self.table.setItem(row_idx, 3, QTableWidgetItem(data["keywords"]))

    def ai_analysis_finished(self, msg):
        QMessageBox.information(self, "AI Generation Complete", msg)
        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_commit.setEnabled(True)
        self.btn_reset.setEnabled(True)
        self.btn_cancel.setVisible(False)
        
        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def commit_grid_to_files(self):
        run_data = []
        for file_path, row_idx in self.grid_data_map.items():
            title = self.table.item(row_idx, 1).text().strip()
            caption = self.table.item(row_idx, 2).text().strip()
            keywords = self.table.item(row_idx, 3).text().strip()
            run_data.append((file_path, title, caption, keywords))

        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_run_ai.setEnabled(False)
        self.btn_commit.setEnabled(False)
        self.btn_reset.setEnabled(False)
        self.btn_cancel.setVisible(True)

        creator = self.creator_input.text().strip()
        copyright_txt = self.copyright_input.text().strip()
        batch_notes = self.context_input.text().strip()
        style = self.style_dropdown.currentText()

        self.start_time = time.time() # Reset clock for commit phase
        
        self.file_worker = FileWriteWorker(run_data, creator, copyright_txt, batch_notes, style, self.app_settings)
        self.file_worker.progress_signal.connect(self.update_progress)
        self.file_worker.log_signal.connect(self.log_output.append)
        self.file_worker.finished_signal.connect(self.file_write_finished)
        self.file_worker.start()

    def file_write_finished(self, msg):
        QMessageBox.information(self, "Commit Finalized", msg)
        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_reset.setEnabled(True)
        self.btn_cancel.setVisible(False)
        
        self.force_clear_workspace()
        self.file_label.setText("Batch processing complete! Check your Documents folder for records.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        files_to_add = []
        folders_to_scan = []
        
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if os.path.isdir(local_path):
                folders_to_scan.append(local_path)
            elif os.path.isfile(local_path):
                files_to_add.append(local_path)
                
        if files_to_add:
            valid_extensions = ('.arw', '.cr2', '.nef', '.dng', '.tiff', '.tif', '.jpg', '.jpeg')
            filtered_files = [f for f in files_to_add if f.lower().endswith(valid_extensions)]
            if filtered_files:
                self.append_to_queue(filtered_files)
                
        for folder in folders_to_scan:
            self.file_label.setText("🔍 Scanning dropped folder for photos...")
            self.folder_scan_worker = FolderScanWorker(folder)
            self.folder_scan_worker.progress_signal.connect(self.on_folder_scan_progress)
            self.folder_scan_worker.files_ready_signal.connect(self.on_folder_scan_complete)
            self.folder_scan_worker.start()
            break

    def test_api_connection(self):
        api_key = self.api_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "API Test", "Please enter an API key first.")
            return
            
        self.btn_test_api.setEnabled(False)
        self.btn_test_api.setText("Testing...")
        
        model_name = self.app_settings.get("gemini_model", "gemini-3.5-flash")
        self.test_worker = APITestWorker(api_key, model_name)
        self.test_worker.result_signal.connect(self.on_api_test_complete)
        self.test_worker.start()
        
    def on_api_test_complete(self, success, message):
        self.btn_test_api.setEnabled(True)
        self.btn_test_api.setText("⚡ Test")
        if success:
            QMessageBox.information(self, "API Test Success", message)
        else:
            QMessageBox.critical(self, "API Test Failed", message)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PhotoMetadataApp()
    window.show()
    sys.exit(app.exec())