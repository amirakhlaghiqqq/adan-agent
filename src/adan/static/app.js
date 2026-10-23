const form = document.querySelector("#query-form");
const questionInput = document.querySelector("#question");
const submitButton = document.querySelector("#submit-button");
const buttonLabel = document.querySelector(".button-label");
const loadingMessage = document.querySelector("#loading-message");
const errorMessage = document.querySelector("#error-message");
const answerPanel = document.querySelector("#answer-panel");
const answerStatus = document.querySelector("#answer-status");
const answerText = document.querySelector("#answer-text");
const citationsSection = document.querySelector("#citations-section");
const citationsList = document.querySelector("#citations-list");
const noCitations = document.querySelector("#no-citations");

const statusLabels = {
  complete: "Complete",
  partial: "Partial answer",
  insufficient_evidence: "Insufficient evidence",
  error: "Error",
};

questionInput.addEventListener("input", () => questionInput.setCustomValidity(""));

function formatCitation(citation) {
  const item = document.createElement("li");
  item.className = "citation-item";

  const source = document.createElement("span");
  source.className = "citation-source";
  source.textContent = citation.source_file || citation.document_id || "Policy source";
  item.append(source);

  const details = [];
  if (citation.section) details.push(citation.section);
  if (citation.page_number) details.push(`Page ${citation.page_number}`);
  else if (Array.isArray(citation.page_numbers) && citation.page_numbers.length) {
    details.push(`Pages ${citation.page_numbers.join(", ")}`);
  }

  if (details.length) {
    const detail = document.createElement("span");
    detail.className = "citation-detail";
    detail.textContent = details.join(" · ");
    item.append(detail);
  }

  return item;
}

function showAnswer(result) {
  const status = statusLabels[result.status] ? result.status : "partial";
  answerStatus.textContent = statusLabels[status];
  answerStatus.dataset.status = status;
  answerText.textContent = result.answer || "No answer was returned.";

  const citations = Array.isArray(result.citations) ? result.citations : [];
  citationsList.replaceChildren(...citations.map(formatCitation));
  citationsSection.hidden = citations.length === 0;
  noCitations.hidden = citations.length !== 0;
  answerPanel.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (submitButton.disabled) return;
  if (!question) {
    questionInput.setCustomValidity("Enter a question.");
    questionInput.reportValidity();
    return;
  }

  submitButton.disabled = true;
  buttonLabel.textContent = "Working…";
  loadingMessage.hidden = false;
  errorMessage.hidden = true;
  answerPanel.hidden = true;

  try {
    const response = await fetch("/api/v1/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!response.ok) throw new Error("The assistant could not process that question.");

    const result = await response.json();
    showAnswer(result);
  } catch {
    errorMessage.textContent = "The assistant is unavailable right now. Please try again.";
    errorMessage.hidden = false;
  } finally {
    loadingMessage.hidden = true;
    submitButton.disabled = false;
    buttonLabel.textContent = "Ask assistant";
  }
});
