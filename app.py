import os
import sys
import json
import time
from datetime import datetime
import google.generativeai as genai
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QTextEdit, QLabel, 
                             QProgressBar, QMessageBox, QLineEdit, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QDialog, QStyle, 
                             QSplitter, QComboBox, QFormLayout, QSpinBox, QDialogButtonBox)
from PyQt6.QtGui import QIcon, QPixmap, QImage
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PIL import Image
import numpy as np

# Disable Pillow's size limit to safely process massive panoramas
Image.MAX_IMAGE_PIXELS = None

import exiftool

CONFIG_FILE_PATH = "config.json"
LOGS_DIR = "logs"

def load_preview_image(file_path):
    """Intelligently load images, using rawpy for proprietary RAWs and Pillow for standard formats."""
    raw_extensions = ['.arw', '.cr2', '.nef', '.dng', '.raf', '.orf']
    if any(file_path.lower().endswith(ext) for ext in raw_extensions):
        try:
            import rawpy
            with rawpy.imread(file_path) as raw:
                # half_size=True cuts memory usage massively and speeds up processing
                rgb = raw.postprocess(use_camera_wb=True, half_size=True)
            return Image.fromarray(rgb)
        except Exception as e:
            print(f"rawpy failed on {file_path}, falling back to standard loader. Error: {e}")
    
    return Image.open(file_path)


class ImagePreviewWorker(QThread):
    """Background worker to prevent UI freezing when loading massive RAW files."""
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
            qim = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
            
            if not self.is_cancelled:
                self.preview_ready_signal.emit(qim, self.file_path)
                
            if hasattr(img, 'close'):
                img.close()
        except Exception as e:
            print(f"Preview generation error: {e}")
            if not self.is_cancelled:
                self.preview_ready_signal.emit(QImage(), self.file_path)


class SettingsDialog(QDialog):
    """A dialog window for configuring AI generation limits."""
    def __init__(self, current_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Generation Settings")
        self.setMinimumWidth(300)
        
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
        
        form_layout.addRow("Max Title Words:", self.title_spin)
        form_layout.addRow("Max Caption Words:", self.caption_spin)
        form_layout.addRow("Max Keywords:", self.keyword_spin)
        
        layout.addLayout(form_layout)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def get_settings(self):
        return {
            "title_max_words": self.title_spin.value(),
            "caption_max_words": self.caption_spin.value(),
            "keyword_max_count": self.keyword_spin.value()
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
            model = genai.GenerativeModel('gemini-2.5-flash')
        except Exception as e:
            self.log_signal.emit(f"✕ API Configuration Error: {str(e)}")
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
        
        with exiftool.ExifToolHelper() as et:
            for index, file_path in enumerate(self.file_paths):
                if not os.path.exists(file_path):
                    continue
                
                base_name = os.path.basename(file_path)
                self.log_signal.emit(f"Analyzing visual assets for: {base_name}...")

                try:
                    gps_ctx, time_ctx = self.get_image_context(et, file_path)
                    
                    img = load_preview_image(file_path)
                    img.thumbnail((1024, 1024))
                    rgb_img = img.convert("RGB")

                    user_context_injection = ""
                    if self.batch_context:
                        user_context_injection = f"CRITICAL USER CONTEXT NOTES: Use this exact context/event/client info to guide details: '{self.batch_context}'\n"

                    prompt = f"""
                    You are an expert photography archivist creating standard Lightroom metadata. I am providing an image taken on {time_ctx} at {gps_ctx}.
                    {user_context_injection}
                    Read any visible text or branding on buildings or subjects. If coordinates are provided, use them for geographical context.
                    
                    Return a JSON object with EXACTLY these three keys: 'title', 'caption', 'keywords'.
                    
                    1. 'title': A highly accurate, production-ready title (max {t_max} words). Describe the primary subject clearly. To avoid repetitive titles in a batch, you MUST include the most prominent unique foreground element or specific angle (e.g., 'Overlooking Train Tracks', 'Close-Up', 'Street Level'). The title MUST read smoothly as a natural, editorial phrase (e.g., 'Aerial View of the Charlotte Skyline at Golden Hour'), rather than a clunky list of keywords. IF the lighting condition is dramatic or highly specific (e.g., 'Golden Hour', 'Blue Hour', 'Night', 'Neon'), include it. Do NOT include generic lighting terms like 'Midday' or 'Daylight' in the title.
                    
                    2. 'caption': A straightforward, factual catalog sentence (maximum {c_max} words) analyzed through the lens of {active_style_guide}. Describe exactly what the subject is, the setting, and the lighting. IF landmarks are visible, explicitly name the 1 or 2 most prominent ones. This MUST be a single, grammatically correct, and flowing sentence. Do NOT use semicolons, lists, or fragmented phrasing. If you hit the word limit, prioritize the main subject over extra adjectives. NEVER use flowery, poetic, or overly artistic language. Just state the facts.
                    
                    3. 'keywords': An array of up to {k_max} highly specific tags. Inject stylistic elements for {active_style_guide}, alongside artistic terms, accurate lighting, location, and core subjects. DO NOT use generic terms like 'picture', 'image', 'photo', or 'daytime'. DO NOT mash words together into camelCase or hashtags. Always use natural spaces between words in a single tag (e.g., use 'North Carolina' instead of 'NorthCarolina'). Ensure all Keywords are formatted in Title Case.
                    """
                    
                    response = model.generate_content(
                        [prompt, rgb_img],
                        generation_config={"response_mime_type": "application/json"}
                    )

                    metadata = json.loads(response.text)
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
                    
                    time.sleep(3) # Rate Limiter

                except Exception as e:
                    self.log_signal.emit(f"✕ Skipping file error on {base_name}: {str(e)}\n")
                
                self.progress_signal.emit(index + 1, total_files)

        self.finished_signal.emit("AI Stage Completed! Review your grid entries and select a row to preview the image.")


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

    def run(self):
        start_time = time.time()
        total_files = len(self.run_data)
        success_count = 0
        
        # Prepare Log File
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR)
        
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        log_filename = os.path.join(LOGS_DIR, f"Batch_Log_{timestamp}.txt")
        
        log_content = f"--- JR AI PHOTO TAGGER : BATCH RUN LOG ---\n"
        log_content += f"Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        log_content += f"Creator: {self.creator} | Copyright: {self.copyright_text}\n"
        log_content += f"AI Style Applied: {self.photo_style}\n"
        log_content += f"AI Limits: Title ({self.settings.get('title_max_words')}w) | Caption ({self.settings.get('caption_max_words')}w) | Keywords ({self.settings.get('keyword_max_count')})\n"
        log_content += f"Batch Notes: {self.batch_context}\n"
        log_content += "="*60 + "\n\n"
        
        with exiftool.ExifToolHelper() as et:
            for index, (file_path, title, caption, kw_str) in enumerate(self.run_data):
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

                    et.set_tags([file_path], tags=tags, params=["-overwrite_original"])
                    success_count += 1
                    self.log_signal.emit(f"💾 Permanently written: {base_name}")
                    
                    log_content += f"File: {base_name}\nTitle: {title}\nCaption: {caption}\nKeywords: {kw_str}\n"
                    log_content += "-"*60 + "\n"
                    
                except Exception as e:
                    self.log_signal.emit(f"✕ Save failed on {base_name}: {str(e)}")
                    log_content += f"File: {base_name} -> FAILED TO WRITE: {str(e)}\n"
                    log_content += "-"*60 + "\n"

                self.progress_signal.emit(index + 1, total_files)

        # Write Batch Summary Footer
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

        self.finished_signal.emit(
            f"Successfully saved metadata directly inside {success_count} of {total_files} file(s)!\n"
            f"A detailed audit log has been saved to the '{LOGS_DIR}' folder.\n\n"
            "🚨 CRITICAL LIGHTROOM REQUIREMENT:\n"
            "1. Open Adobe Lightroom Classic.\n"
            "2. Highlight these processed photos.\n"
            "3. In the top menu bar, select: Metadata -> Read Metadata from File."
        )


class PhotoMetadataApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_files = []
        self.grid_data_map = {}
        self.start_time = None
        self.current_preview_pixmap = None
        self.preview_worker = None
        
        self.app_settings = {
            "title_max_words": 7, 
            "caption_max_words": 15,
            "keyword_max_count": 25
        }
        
        self.init_ui()
        self.load_config()
        self.check_exiftool()

    def check_exiftool(self):
        """Startup check to ensure ExifTool is installed on the user's system."""
        try:
            with exiftool.ExifToolHelper() as et:
                pass
        except Exception:
            QMessageBox.critical(self, "Missing Dependency: ExifTool", 
                                 "ExifTool is not installed or cannot be found!\n\n"
                                 "This app requires ExifTool to save metadata safely.\n"
                                 "Please download the MacOS Package from exiftool.org and restart the app.")

    def init_ui(self):
        self.setWindowTitle("JR AI Photo Tagger")
        self.resize(1300, 850)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))

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
        row1.addWidget(QLabel("API Key:"))
        row1.addWidget(self.api_input, 2)
        
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
                    self.api_input.setText(data.get("api_key", ""))
                    self.creator_input.setText(data.get("creator", ""))
                    self.copyright_input.setText(data.get("copyright", ""))
                    self.app_settings["title_max_words"] = data.get("title_max_words", 7)
                    self.app_settings["caption_max_words"] = data.get("caption_max_words", 15)
                    self.app_settings["keyword_max_count"] = data.get("keyword_max_count", 25)
            except Exception:
                pass

    def save_config(self):
        config_data = {
            "api_key": self.api_input.text().strip(),
            "creator": self.creator_input.text().strip(),
            "copyright": self.copyright_input.text().strip(),
            "title_max_words": self.app_settings["title_max_words"],
            "caption_max_words": self.app_settings["caption_max_words"],
            "keyword_max_count": self.app_settings["keyword_max_count"]
        }
        try:
            with open(CONFIG_FILE_PATH, "w") as f:
                json.dump(config_data, f)
        except Exception:
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
            self.preview_label.setText("Preview unavailable for this file format.")
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
            "<h3>📋 JR AI Photo Tagger Manual (macOS Edition)</h3><hr>"
            "<b>1. Setup & Configuration:</b> Enter your Gemini API key, Creator name, and Copyright details. These profiles securely save to disk locally.<br><br>"
            "<b>2. Adjusting AI Directives:</b> Click <b>⚙️ Settings</b> to establish word limits. Use the <b>AI Style</b> dropdown to change the semantic parsing perspective (e.g., Drone vs. Street Photography).<br><br>"
            "<b>3. The Power of 'Batch Notes':</b> The AI only reads pixels and EXIF parameters. It cannot know client names or project details. Use the <b>Batch Notes</b> field to supply off-camera context <i>(e.g., 'Juneberry Jams Concert' or 'Nike Spring Catalog')</i> so the AI seamlessly links this data into captions and tags.<br><br>"
            "<b>4. Compiling the Queue:</b> Build batches dynamically using <b>+ Add Files</b> and <b>+ Add Folder</b>. You can repeatedly add multiple folders to create deep processing pipelines. The application auto-filters files for RAW sensor files (Sony ARW, Canon CR2, Nikon NEF, DNG), TIFFs, and JPEGs.<br><br>"
            "<b>5. Live Auditing & Correction:</b> Run the AI engine. Select any row to fire up fluid background preview frames and read formatted metadata card strings instantly. Double-click spreadsheet fields to execute swift edits or append corrections manually.<br><br>"
            "<b>6. Writing & Audit Logs:</b> Click <b>Commit Changes</b> to have ExifTool embed data directly into file metadata headers. Every commit run automatically creates a comprehensive tracking log inside the local 'logs' directory, recording runtime parameters, bounds, and write results.<br><br>"
            "<b>7. Lightroom Syncing:</b> To map the files into Lightroom Classic, highlight your batch folder, right-click, and select <b>Metadata -> Read Metadata from File</b>."
        )
        dialog = QDialog(self)
        dialog.setWindowTitle("Workspace Documentation")
        dialog_layout = QVBoxLayout()
        text_widget = QTextEdit()
        text_widget.setHtml(help_text)
        text_widget.setReadOnly(True)
        text_widget.setMinimumSize(500, 520)
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

    def add_folder(self):
        if not self.check_unsaved_changes():
            return
            
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            valid_extensions = ('.arw', '.cr2', '.nef', '.dng', '.tiff', '.tif', '.jpg', '.jpeg')
            new_files = []
            
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith(valid_extensions):
                        new_files.append(os.path.join(root, file))
            QApplication.restoreOverrideCursor()
            
            if new_files:
                self.append_to_queue(new_files)
            else:
                QMessageBox.information(self, "No Photos Found", "No supported photo files were found in that folder.")

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
            QMessageBox.warning(self, "Missing API Key", "Please paste your Gemini API key.")
            return

        self.save_config()
        self.start_time = time.time()

        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_run_ai.setEnabled(False)
        self.btn_commit.setEnabled(False)
        self.btn_reset.setEnabled(False)
        
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
        
        self.force_clear_workspace()
        self.file_label.setText("Batch processing complete! Check 'logs' folder for records.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PhotoMetadataApp()
    window.show()
    sys.exit(app.exec())