const uploadForm = document.querySelector("#upload-form");
const fileInput = document.querySelector("#file-input");
const uploadButton = document.querySelector("#upload-button");
const refreshFiles = document.querySelector("#refresh-files");
const fileList = document.querySelector("#file-list");
const fileStatus = document.querySelector("#file-status");
const fileError = document.querySelector("#file-error");
const fileCount = document.querySelector("#file-count");

async function filesRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The file request failed.");
  return data;
}

function showFileError(error) {
  fileError.textContent = error instanceof TypeError
    ? "Cannot reach the file manager. Check that Flask is running."
    : error.message;
  fileError.hidden = false;
}

async function loadFiles() {
  const data = await filesRequest("/api/files");
  fileList.replaceChildren();
  fileCount.textContent = `(${data.files.length})`;
  for (const file of data.files) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = `/api/files/${encodeURIComponent(file.id)}`;
    link.textContent = file.name;
    link.download = file.name;
    const size = document.createElement("span");
    size.textContent = file.size < 1024 ? `${file.size} B`
      : file.size < 1024 * 1024 ? `${(file.size / 1024).toFixed(1)} KiB`
      : `${(file.size / (1024 * 1024)).toFixed(1)} MiB`;
    const indexed = document.createElement("span");
    indexed.textContent = file.indexed ? "Ready for questions" : "Not indexed - click Index documents";
    item.append(link, size, indexed);
    fileList.append(item);
  }
  fileStatus.textContent = data.files.length ? "" : "No files yet. Upload a file to get started.";
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file || uploadButton.disabled) return;
  fileError.hidden = true;
  if (file.size >= 20 * 1024 * 1024) {
    showFileError(new Error("Choose a file smaller than 20 MiB."));
    return;
  }
  const body = new FormData();
  body.append("file", file);
  uploadButton.disabled = fileInput.disabled = refreshFiles.disabled = true;
  fileStatus.textContent = "Uploading and indexing...";
  try {
    await filesRequest("/api/files", { method: "POST", body });
    uploadForm.reset();
    fileStatus.textContent = "Uploaded successfully.";
    try {
      await loadFiles();
      fileStatus.textContent = "Uploaded successfully.";
    } catch {
      showFileError(new Error("File uploaded, but the list could not be refreshed. Click Refresh."));
    }
  } catch (error) {
    fileStatus.textContent = "";
    showFileError(error);
  } finally {
    uploadButton.disabled = fileInput.disabled = refreshFiles.disabled = false;
  }
});

refreshFiles.addEventListener("click", async () => {
  fileError.hidden = true;
  refreshFiles.disabled = true;
  try {
    await loadFiles();
  } catch (error) {
    showFileError(error);
  } finally {
    refreshFiles.disabled = false;
  }
});

loadFiles().catch(showFileError);

const indexFiles = document.querySelector("#index-files");
indexFiles.addEventListener("click", async () => {
  indexFiles.disabled = uploadButton.disabled = refreshFiles.disabled = true;
  fileError.hidden = true;
  fileStatus.textContent = "Indexing documents. This may take a few minutes...";
  try {
    const data = await filesRequest("/api/files/index", { method: "POST" });
    await loadFiles();
    const failures = data.results.filter((item) => !item.indexed);
    fileStatus.textContent = `Indexed ${data.results.length - failures.length} documents.`;
    if (failures.length) throw new Error(failures.map((item) => `${item.name}: ${item.error}`).join("; "));
  } catch (error) {
    showFileError(error);
  } finally {
    indexFiles.disabled = uploadButton.disabled = refreshFiles.disabled = false;
  }
});
