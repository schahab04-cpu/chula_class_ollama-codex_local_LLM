const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#file-input");
const dropzone = document.querySelector("#dropzone");
const refreshFiles = document.querySelector("#refresh-files");
const fileList = document.querySelector("#file-list");
const fileStatus = document.querySelector("#file-status");
const fileError = document.querySelector("#file-error");
const fileCount = document.querySelector("#file-count");
const uploadDialog = document.querySelector("#upload-dialog");
const uploadInput = document.querySelector("#upload-input");
const uploadDropzone = document.querySelector("#upload-dropzone");
const uploadStatus = document.querySelector("#upload-status");
const uploadError = document.querySelector("#upload-error");
// Each drop box reports into its own status and error lines.
const panelReport = { status: fileStatus, error: fileError };
const dialogReport = { status: uploadStatus, error: uploadError };
const previewDialog = document.querySelector("#preview-dialog");
const previewTitle = document.querySelector("#preview-title");
const previewFrame = document.querySelector("#preview-frame");
const previewDownload = document.querySelector("#preview-download");
const previewClose = document.querySelector("#preview-close");
let filesBusy = false;
// True while the server indexes or summarizes documents; chat and voice wait for it.
let documentsReading = false;

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

function showFileError(error, report = panelReport) {
  report.error.textContent = fileErrorMessage(error);
  report.error.hidden = false;
}

function setReading(busy, detail = "") {
  const finished = documentsReading && !busy;
  documentsReading = busy;
  document.dispatchEvent(new CustomEvent("documents-busy", { detail: { busy, detail } }));
  if (finished) loadFiles().catch(showFileError);
}

async function checkReading() {
  try {
    const data = await filesRequest("/api/documents/status");
    setReading(data.busy, data.detail);
  } catch {
    // The status poll is advisory; the server still refuses questions while busy.
  }
}

async function pollReading() {
  await checkReading();
  setTimeout(pollReading, documentsReading ? 1000 : 4000);
}

function setBusy(value) {
  filesBusy = value;
  fileInput.disabled = uploadInput.disabled = refreshFiles.disabled = value;
  dropzone.setAttribute("aria-busy", String(value));
  uploadDropzone.setAttribute("aria-busy", String(value));
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
    indexed.className = file.indexed ? "file-ready" : file.error ? "file-failed" : "file-not-ready";
    indexed.textContent = file.indexed ? "Ready for questions"
      : file.error ? `Could not be read: ${file.error}` : "Reading…";
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

async function uploadFiles(files, report = panelReport) {
  if (filesBusy || !files.length) return false;
  const failures = [];
  const duplicates = [];
  report.error.hidden = true;
  setBusy(true);
  try {
    for (const [index, file] of files.entries()) {
      report.status.textContent = `Uploading and reading ${index + 1} of ${files.length}: ${file.name}`;
      // Lock chat and voice right away rather than waiting for the next status poll.
      setReading(true, `Reading ${file.name}`);
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
    fileInput.value = uploadInput.value = "";
    await loadFiles();
    const uploaded = files.length - failures.length - duplicates.length;
    const summary = uploaded
      ? `${uploaded} of ${files.length} document${files.length === 1 ? " is" : "s are"} ready for questions.`
      : "No new documents were uploaded.";
    report.status.textContent = duplicates.length ? `${summary} Already uploaded: ${duplicates.join(", ")}.` : summary;
    if (failures.length) showFileError(new Error(failures.join("\n")), report);
    return !failures.length;
  } catch (error) {
    showFileError(error, report);
    return false;
  } finally {
    setBusy(false);
    await checkReading();
  }
}

// Opened when the user asks to upload, by voice or in chat.
function openUploadDialog() {
  uploadStatus.textContent = "";
  uploadError.hidden = true;
  if (!uploadDialog.open) uploadDialog.showModal();
  uploadDropzone.focus();
}

async function uploadFromDialog(files) {
  const succeeded = await uploadFiles(files, dialogReport);
  // Close once everything is ready, so the conversation can carry on.
  if (succeeded) setTimeout(() => uploadDialog.close(), 1500);
}

uploadForm.addEventListener("submit", (event) => event.preventDefault());
fileInput.addEventListener("change", () => uploadFiles(Array.from(fileInput.files)));
uploadInput.addEventListener("change", () => uploadFromDialog(Array.from(uploadInput.files)));
document.querySelector("#upload-close").addEventListener("click", () => uploadDialog.close());

// Both drop boxes share the page-level drag handlers; this finds the one under the pointer.
function zoneFor(target) {
  if (uploadDialog.open) return uploadDropzone.contains(target) ? uploadDropzone : null;
  return dropzone.contains(target) ? dropzone : null;
}

function isFileDrag(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

document.addEventListener("dragover", (event) => {
  if (!isFileDrag(event)) return;
  event.preventDefault();
  const zone = zoneFor(event.target);
  const accepted = Boolean(zone) && !filesBusy;
  event.dataTransfer.dropEffect = accepted ? "copy" : "none";
  for (const each of [dropzone, uploadDropzone]) each.classList.toggle("is-dragging", accepted && each === zone);
}, true);

document.addEventListener("dragleave", (event) => {
  if (isFileDrag(event) && !zoneFor(event.relatedTarget)) {
    dropzone.classList.remove("is-dragging");
    uploadDropzone.classList.remove("is-dragging");
  }
}, true);

document.addEventListener("drop", (event) => {
  if (!isFileDrag(event)) return;
  event.preventDefault();
  dropzone.classList.remove("is-dragging");
  uploadDropzone.classList.remove("is-dragging");
  const zone = zoneFor(event.target);
  if (!zone || filesBusy) return;
  const report = zone === uploadDropzone ? dialogReport : panelReport;
  const files = Array.from(event.dataTransfer.files || []);
  if (!files.length) {
    showFileError(new Error("The dropped files could not be read. Try choosing them from the file picker."), report);
    return;
  }
  if (zone === uploadDropzone) uploadFromDialog(files);
  else uploadFiles(files);
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

loadFiles().catch(showFileError);
pollReading();
