const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#file-input");
const dropzone = document.querySelector("#dropzone");
const refreshFiles = document.querySelector("#refresh-files");
const fileList = document.querySelector("#file-list");
const fileStatus = document.querySelector("#file-status");
const fileError = document.querySelector("#file-error");
const fileCount = document.querySelector("#file-count");
const indexFiles = document.querySelector("#index-files");
const previewDialog = document.querySelector("#preview-dialog");
const previewTitle = document.querySelector("#preview-title");
const previewFrame = document.querySelector("#preview-frame");
const previewDownload = document.querySelector("#preview-download");
const previewClose = document.querySelector("#preview-close");
let filesBusy = false;

async function filesRequest(url, options) {
  const response = await fetch(url, options);
  const data = response.status === 204 ? {} : await response.json().catch(() => null);
  if (!response.ok || !data) throw new Error(data?.error || `The file request failed (HTTP ${response.status}).`);
  return data;
}

function fileErrorMessage(error) {
  return error instanceof TypeError
    ? "Cannot reach the file manager. Check that Flask is running."
    : error.message;
}

function showFileError(error) {
  fileError.textContent = fileErrorMessage(error);
  fileError.hidden = false;
}

function setBusy(value) {
  filesBusy = value;
  fileInput.disabled = refreshFiles.disabled = indexFiles.disabled = value;
  dropzone.setAttribute("aria-busy", String(value));
  fileList.querySelectorAll("button").forEach((button) => { button.disabled = value; });
}

async function loadFiles() {
  const data = await filesRequest("/api/files");
  fileList.replaceChildren();
  fileCount.textContent = `(${data.files.length})`;
  for (const file of data.files) {
    const item = document.createElement("li");
    const details = document.createElement("div");
    details.className = "file-details";
    const link = document.createElement("a");
    link.href = `/api/files/${encodeURIComponent(file.id)}`;
    link.textContent = file.name;
    link.download = file.name;
    if (file.name.toLowerCase().endsWith(".pdf")) link.dataset.previewId = file.id;
    const size = document.createElement("span");
    size.textContent = file.size < 1024 ? `${file.size} B`
      : file.size < 1024 * 1024 ? `${(file.size / 1024).toFixed(1)} KiB`
      : `${(file.size / (1024 * 1024)).toFixed(1)} MiB`;
    const indexed = document.createElement("span");
    indexed.className = file.indexed ? "file-ready" : "file-not-ready";
    indexed.textContent = file.indexed ? "Ready for questions" : "Not indexed";
    details.append(link, size, indexed);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-file";
    remove.dataset.fileId = file.id;
    remove.disabled = filesBusy;
    remove.setAttribute("aria-label", `Remove ${file.name}`);
    remove.title = `Remove ${file.name}`;
    remove.textContent = "×";
    item.append(details, remove);
    fileList.append(item);
  }
  fileStatus.textContent = data.files.length ? "" : "No documents yet. Drop files here to get started.";
}

async function uploadFiles(files) {
  if (filesBusy || !files.length) return;
  const failures = [];
  const duplicates = [];
  fileError.hidden = true;
  setBusy(true);
  try {
    for (const [index, file] of files.entries()) {
      fileStatus.textContent = `Uploading and indexing ${index + 1} of ${files.length}: ${file.name}`;
      if (file.size >= 20 * 1024 * 1024) {
        failures.push(`${file.name}: choose a file smaller than 20 MiB.`);
        continue;
      }
      const body = new FormData();
      body.append("file", file);
      try {
        const result = await filesRequest("/api/files", { method: "POST", body });
        if (result.duplicate) duplicates.push(file.name);
      } catch (error) {
        failures.push(`${file.name}: ${fileErrorMessage(error)}`);
      }
    }
    fileInput.value = "";
    await loadFiles();
    const uploaded = files.length - failures.length - duplicates.length;
    const summary = uploaded
      ? `Uploaded and indexed ${uploaded} of ${files.length} document${files.length === 1 ? "" : "s"}.`
      : "No new documents were uploaded.";
    fileStatus.textContent = duplicates.length ? `${summary} Already uploaded: ${duplicates.join(", ")}.` : summary;
    if (failures.length) showFileError(new Error(failures.join("\n")));
  } catch (error) {
    showFileError(error);
  } finally {
    setBusy(false);
  }
}

uploadForm.addEventListener("submit", (event) => event.preventDefault());
fileInput.addEventListener("change", () => uploadFiles(Array.from(fileInput.files)));

function isFileDrag(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

document.addEventListener("dragover", (event) => {
  if (!isFileDrag(event)) return;
  event.preventDefault();
  const accepted = dropzone.contains(event.target) && !filesBusy;
  event.dataTransfer.dropEffect = accepted ? "copy" : "none";
  dropzone.classList.toggle("is-dragging", accepted);
}, true);

document.addEventListener("dragleave", (event) => {
  if (isFileDrag(event) && !dropzone.contains(event.relatedTarget)) {
    dropzone.classList.remove("is-dragging");
  }
}, true);

document.addEventListener("drop", (event) => {
  if (!isFileDrag(event)) return;
  event.preventDefault();
  dropzone.classList.remove("is-dragging");
  if (!dropzone.contains(event.target) || filesBusy) return;
  const files = Array.from(event.dataTransfer.files || []);
  if (!files.length) {
    showFileError(new Error("The dropped files could not be read. Try choosing them from the file picker."));
    return;
  }
  uploadFiles(files);
}, true);

refreshFiles.addEventListener("click", async () => {
  fileError.hidden = true;
  refreshFiles.disabled = true;
  try {
    await loadFiles();
  } catch (error) {
    showFileError(error);
  } finally {
    refreshFiles.disabled = filesBusy;
  }
});

function openPreview(link) {
  previewTitle.textContent = link.textContent;
  previewFrame.title = `Preview of ${link.textContent}`;
  previewFrame.src = `/api/files/${encodeURIComponent(link.dataset.previewId)}/preview`;
  previewDownload.href = link.href;
  previewDownload.download = link.download;
  previewDialog.showModal();
}

fileList.addEventListener("click", (event) => {
  const link = event.target.closest("a[data-preview-id]");
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  openPreview(link);
});

previewClose.addEventListener("click", () => previewDialog.close());
previewDialog.addEventListener("click", (event) => {
  if (event.target === previewDialog) previewDialog.close();
});
previewDialog.addEventListener("close", () => previewFrame.removeAttribute("src"));

fileList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-file-id]");
  if (!button || filesBusy) return;
  const fileName = button.getAttribute("aria-label").replace(/^Remove /, "");
  fileError.hidden = true;
  setBusy(true);
  fileStatus.textContent = `Removing ${fileName}...`;
  try {
    await filesRequest(`/api/files/${encodeURIComponent(button.dataset.fileId)}`, { method: "DELETE" });
    await loadFiles();
    fileStatus.textContent = `Removed ${fileName}.`;
  } catch (error) {
    showFileError(error);
  } finally {
    setBusy(false);
  }
});

indexFiles.addEventListener("click", async () => {
  setBusy(true);
  fileError.hidden = true;
  fileStatus.textContent = "Indexing documents. This may take a few minutes...";
  try {
    const data = await filesRequest("/api/files/index", { method: "POST" });
    await loadFiles();
    const failures = data.results.filter((item) => !item.indexed);
    fileStatus.textContent = `Indexed ${data.results.length - failures.length} documents.`;
    if (failures.length) showFileError(new Error(failures.map((item) => `${item.name}: ${item.error}`).join("\n")));
  } catch (error) {
    showFileError(error);
  } finally {
    setBusy(false);
  }
});

loadFiles().catch(showFileError);
