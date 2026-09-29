// A drop zone, its "Choose folder" button and its typed-path box: in the
// analysis and in calibration. A dropped or chosen folder is copied to the
// server first; `open` is then called with the server-side folder. Which files
// are copied, and where to, is the server's choice (classes/upload_plan.py).

class FolderPicker {
  // Dropping a folder anywhere else on the page should not navigate away to it.
  static guardWindow() {
    window.addEventListener("dragover", (event) => event.preventDefault());
    window.addEventListener("drop", (event) => event.preventDefault());
  }

  // Walk a dropped folder into a flat list of { path, file }, paths relative to it.
  static async filesFromDrop(dataTransfer) {
    const entries = [...dataTransfer.items].map((item) => item.webkitGetAsEntry && item.webkitGetAsEntry()).filter(Boolean);
    if (entries.length !== 1 || !entries[0].isDirectory) {
      throw new Error("Drop one folder: the one that holds the recording folders.");
    }
    const root = entries[0];
    const files = [];
    const walk = async (dir, prefix) => {
      const reader = dir.createReader();
      let batch;
      do {
        batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        for (const entry of batch) {
          if (entry.isDirectory) await walk(entry, `${prefix}${entry.name}/`);
          else files.push({ path: prefix + entry.name, file: await new Promise((res, rej) => entry.file(res, rej)) });
        }
      } while (batch.length);
    };
    await walk(root, "");
    return { name: root.name, files };
  }

  static filesFromPicker(fileList) {
    const all = [...fileList];
    if (!all.length) throw new Error("That folder is empty.");
    const name = all[0].webkitRelativePath.split("/")[0];
    return { name, files: all.map((file) => ({ path: file.webkitRelativePath.split("/").slice(1).join("/"), file })) };
  }

  // `prefix` picks the elements ("" in the analysis, "cal-" in calibration).
  constructor(prefix, open) {
    this.prefix = prefix;
    this.open = open;
    this.wire();
  }

  element(name) {
    return $(`${this.prefix}${name}`);
  }

  wire() {
    const dropZone = this.element("drop-zone");
    const input = this.element("folder-input");
    const path = this.element("data-dir");
    ["dragenter", "dragover"].forEach((type) =>
      dropZone.addEventListener(type, (event) => { event.preventDefault(); dropZone.classList.add("dragging"); }));
    ["dragleave", "drop"].forEach((type) =>
      dropZone.addEventListener(type, (event) => {
        if (type === "dragleave" && dropZone.contains(event.relatedTarget)) return;
        dropZone.classList.remove("dragging");
      }));
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      const transfer = event.dataTransfer;
      this.handleFolder(() => FolderPicker.filesFromDrop(transfer));
    });

    this.element("browse-btn").addEventListener("click", () => input.click());
    dropZone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target === dropZone) input.click();
    });
    input.addEventListener("change", (event) => {
      const list = event.target.files;
      this.handleFolder(async () => FolderPicker.filesFromPicker(list));
      event.target.value = "";
    });
    this.element("open-btn").addEventListener("click", () => this.open(path.value.trim()));
    path.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this.open(path.value.trim());
    });
  }

  async handleFolder(getFolder) {
    const status = this.element("open-status");
    status.className = "hint";
    status.textContent = "";
    try {
      await this.upload(await getFolder());
    } catch (error) {
      this.element("upload-progress").hidden = true;
      status.className = "hint error";
      status.textContent = error.message;
    }
  }

  // Copy the files the server asks for, a few at a time, then open the folder.
  async upload({ name: dropped, files }) {
    const progress = this.element("upload-progress");
    const bar = this.element("upload-bar");
    const text = this.element("upload-text");
    progress.hidden = false;
    bar.style.width = "0%";
    text.textContent = `Checking ${files.length} files…`;

    const manifest = await post(`/api/uploads/${encodeURIComponent(dropped)}/manifest`, {
      files: files.map((f) => ({ path: f.path, size: f.file.size })),
    });
    const { name } = manifest;
    const byPath = new Map(files.map((f) => [f.path, f.file]));
    const queue = manifest.missing.map(({ path, target }) => ({ file: byPath.get(path), target }));
    const totalBytes = queue.reduce((sum, f) => sum + f.file.size, 0);
    const totalFiles = queue.length;
    let sentBytes = 0;
    let sentFiles = 0;

    const report = () => {
      const fraction = totalBytes ? sentBytes / totalBytes : 1;
      bar.style.width = `${fraction * 100}%`;
      text.textContent = totalFiles
        ? `Copying “${name}”: ${sentFiles} of ${totalFiles} files (${(sentBytes / 1e6).toFixed(0)} of ${(totalBytes / 1e6).toFixed(0)} MB)`
        : `“${name}” is already here.`;
    };
    report();

    // A few uploads in flight at once keeps the local disk busy without flooding it.
    const worker = async () => {
      while (queue.length) {
        const item = queue.shift();
        const response = await fetch(
          `/api/uploads/${encodeURIComponent(name)}/file?path=${encodeURIComponent(item.target)}`,
          { method: "PUT", body: item.file },
        );
        if (!response.ok) throw new Error(`Upload failed for ${item.target}`);
        sentBytes += item.file.size;
        sentFiles += 1;
        report();
      }
    };
    await Promise.all([worker(), worker(), worker(), worker()]);
    text.textContent = `Copied “${name}”. Opening…`;
    await this.open(manifest.data_dir);
    progress.hidden = true;
  }
}
