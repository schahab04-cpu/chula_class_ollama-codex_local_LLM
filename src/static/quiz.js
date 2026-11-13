// Renders a multiple-choice quiz from /api/chat or a voice "quiz" event. Clicking an option
// reveals whether it was right, the explanation and the source passage; a score follows.
// All text goes through textContent: quiz text comes from the model and the documents.
function renderQuiz(quiz) {
  const section = document.createElement("section");
  section.className = "quiz";
  const title = document.createElement("h3");
  title.className = "quiz-title";
  title.textContent = quiz.title;
  const score = document.createElement("p");
  score.className = "quiz-score";
  const total = quiz.questions.length;
  let answered = 0;
  let correct = 0;
  const showScore = () => {
    score.textContent = answered < total
      ? `${answered} of ${total} answered · ${correct} correct`
      : `Done: ${correct} of ${total} correct${correct === total ? ". Perfect." : "."}`;
  };
  showScore();
  const list = document.createElement("ol");
  list.className = "quiz-questions";

  for (const item of quiz.questions) {
    const entry = document.createElement("li");
    entry.className = "quiz-question";
    const question = document.createElement("p");
    question.className = "quiz-prompt";
    question.textContent = item.question;
    const options = document.createElement("div");
    options.className = "quiz-options";
    options.setAttribute("role", "group");
    options.setAttribute("aria-label", item.question);
    const feedback = document.createElement("div");
    feedback.className = "quiz-feedback";
    feedback.setAttribute("aria-live", "polite");
    feedback.hidden = true;

    const buttons = item.options.map((option, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quiz-option";
      const letter = document.createElement("span");
      letter.className = "quiz-letter";
      letter.textContent = "ABCD"[index] || String(index + 1);
      button.append(letter, document.createTextNode(option));
      button.addEventListener("click", () => {
        const right = index === item.answer;
        for (const [other, otherButton] of buttons.entries()) {
          otherButton.disabled = true;
          if (other === item.answer) otherButton.classList.add("is-correct");
        }
        if (!right) button.classList.add("is-wrong");
        button.setAttribute("aria-pressed", "true");
        answered += 1;
        if (right) correct += 1;
        const verdict = document.createElement("strong");
        verdict.textContent = right ? "Correct. " : `Not quite: the answer is ${item.options[item.answer]}. `;
        const why = document.createElement("span");
        why.textContent = item.explanation;
        feedback.replaceChildren(verdict, why);
        if (item.source) {
          const details = document.createElement("details");
          const summary = document.createElement("summary");
          summary.textContent = `Source: ${item.source.name}, ${item.source.location}`;
          const excerpt = document.createElement("p");
          excerpt.textContent = item.source.quote;
          details.append(summary, excerpt);
          feedback.append(details);
        }
        feedback.hidden = false;
        showScore();
      });
      options.append(button);
      return button;
    });

    entry.append(question, options, feedback);
    list.append(entry);
  }

  section.append(title, score, list);
  return section;
}
