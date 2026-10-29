const form = document.querySelector("#chat-form");
const prompt = document.querySelector("#prompt");
const conversation = document.querySelector("#conversation");
const send = document.querySelector("#send");
const clear = document.querySelector("#clear");
const status = document.querySelector("#status");
const error = document.querySelector("#error");
let messages = [];
let busy = false;

function appendLinkedText(element, content) {
  let offset = 0;
  for (const match of content.matchAll(/https?:\/\/[^\s<>"']+/gi)) {
    let url = match[0].replace(/[.,!?;:]+$/, "");
    // Leave sentence punctuation and Markdown's closing brackets outside links.
    while (/[)\]}]$/.test(url)) {
      const closing = url.at(-1);
      const opening = { ")": "(", "]": "[", "}": "{" }[closing];
      if (url.split(closing).length <= url.split(opening).length) break;
      url = url.slice(0, -1).replace(/[.,!?;:]+$/, "");
    }
    try {
      const parsed = new URL(url);
      if (!["http:", "https:"].includes(parsed.protocol)) continue;
    } catch {
      continue;
    }
    element.append(document.createTextNode(content.slice(offset, match.index)));
    const link = document.createElement("a");
    link.href = url;
    link.textContent = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    element.append(link);
    offset = match.index + url.length;
  }
  element.append(document.createTextNode(content.slice(offset)));
}

function appendMessage(role, content, sources = []) {
  document.querySelector("#empty")?.remove();
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const label = document.createElement("strong");
  label.textContent = role === "user" ? "You" : "Gemma";
  const text = document.createElement("p");
  if (role === "assistant") {
    appendLinkedText(text, content);
  } else {
    text.textContent = content;
  }
  article.append(label, text);
  for (const [index, source] of sources.entries()) {
    const link = document.createElement("a");
    link.href = `/api/files/${encodeURIComponent(source.file_id)}`;
    link.textContent = `[${index + 1}] ${source.name} - ${source.location}`;
    link.download = source.name;
    const reference = document.createElement("p");
    reference.append(link);
    article.append(reference);
  }
  conversation.append(article);
  conversation.scrollTop = conversation.scrollHeight;
  return article;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = prompt.value.trim();
  if (busy || !content) return;
  busy = true;
  send.disabled = clear.disabled = prompt.disabled = true;
  error.hidden = true;
  status.textContent = "Searching documents and checking evidence...";
  const pending = { role: "user", content };
  const bubble = appendMessage("user", content);
  prompt.value = "";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [...messages, pending] }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The request failed. Please try again.");
    if (typeof data.message?.content !== "string") throw new Error("The server returned an invalid answer.");
    messages.push(pending, data.message);
    appendMessage("assistant", data.message.content, data.sources || []);
  } catch (failure) {
    bubble.remove();
    prompt.value = content;
    error.textContent = failure instanceof TypeError
      ? "Cannot reach the chat server. Check that Flask is running, then try again."
      : failure.message;
    error.hidden = false;
  } finally {
    busy = false;
    send.disabled = clear.disabled = prompt.disabled = false;
    status.textContent = "";
    prompt.focus();
  }
});

prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

clear.addEventListener("click", () => {
  messages = [];
  conversation.replaceChildren();
  error.hidden = true;
  prompt.value = "";
  prompt.focus();
});
