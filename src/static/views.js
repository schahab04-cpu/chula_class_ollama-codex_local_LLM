const chatView = document.querySelector("#chat-view");
const filesView = document.querySelector("#files-view");
const chatButton = document.querySelector("#open-chat");
const filesButton = document.querySelector("#open-files");

function showView(showFiles) {
  chatView.hidden = showFiles;
  filesView.hidden = !showFiles;
  chatButton.setAttribute("aria-pressed", String(!showFiles));
  filesButton.setAttribute("aria-pressed", String(showFiles));
  chatButton.classList.toggle("secondary", showFiles);
  filesButton.classList.toggle("secondary", !showFiles);
}

chatButton.addEventListener("click", () => showView(false));
filesButton.addEventListener("click", () => showView(true));
