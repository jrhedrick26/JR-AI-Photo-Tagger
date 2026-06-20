# JR AI Photo Tagger 📸🤖

An open-source, professional-grade desktop workspace that leverages Google's Gemini 2.5 Flash AI to automatically generate highly accurate, contextual, and editorial Titles, Captions, and Keywords for your photography batches. 

It reads camera EXIF/GPS context and safely writes metadata directly inside your JPEGs, TIFFs, DNGs, and proprietary RAW formats (Sony ARW, Canon CR2, Nikon NEF) using industry-standard ExifTool.

---

## 🍏 macOS Installation Guide (No Terminal Required)

**1. Install the ExifTool Engine**
The app relies on ExifTool to bake metadata safely into your photos without altering image pixels.
* Go to the official website: [exiftool.org](https://exiftool.org/).
* Download and run the **macOS Package (.pkg)** installer to set up the background engine.

**2. Download the App Installer**
* Go to the **Releases** section on the right-hand sidebar of this GitHub repository page.
* Download the **`JR_AI_Photo_Tagger.dmg`** file.
* Double-click the downloaded `.dmg` file to open the installer window, then drag the **JR AI Photo Tagger.app** icon and drop it directly into your Mac's **Applications** folder.

**3. Fire Up the App (First-Time Security Bypass)**
Because this is open-source software distributed outside the official Apple App Store, macOS will show a security block when you first try to open it. To authorize it, follow these quick steps:
1. Double-click the app icon inside your **Applications** folder. When the warning box pops up stating it cannot be verified, click **Done**.
2. Click the **Apple icon ()** in the top-left corner of your Mac screen and choose **System Settings...**
3. Navigate to **Privacy & Security** on the left sidebar, then scroll down on the right side until you see the **Security** heading.
4. Look for the message stating *"JR AI Photo Tagger.app was blocked from use..."* and click the **Open Anyway** button next to it.
5. Provide your Mac user password or Touch ID, then click **Open** on the final confirmation card.

*Note: You only have to do this once! Your Mac will permanently remember this exception, and you can double-click the app icon to run it normally going forward.*

---

## 🪟 Windows Installation Guide (No Terminal Required)

**1. Set Up Your App Folder**
* Create a brand new folder on your computer named `JR AI Photo Tagger` (e.g., in your Documents or Desktop).

**2. Download the App Executable**
* Go to the **Releases** section on the right-hand sidebar of this GitHub repository page.
* Download the **`JR_AI_Photo_Tagger.exe`** file.
* Move the downloaded `.exe` file straight into the new folder you just created.

**3. Download the ExifTool Engine**
Windows requires placing the ExifTool engine directly alongside the application executable.
* Go to the official website: [exiftool.org](https://exiftool.org/).
* Download the **Windows Executable** zip file (e.g., `exiftool-XX.XX.zip`).
* Unzip it, find the file named `exiftool(-k).exe`, and drag it into your application folder.
* **CRITICAL STEP:** Rename that file from `exiftool(-k).exe` to exactly **`exiftool.exe`**.

Your folder should now look like this:
```text
📂 JR AI Photo Tagger
 ├── 📄 JR_AI_Photo_Tagger.exe
 └── 📄 exiftool.exe
