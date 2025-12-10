document.addEventListener("DOMContentLoaded", () => {
  // --------------------------------------
  // Auto-dismiss flash messages
  // --------------------------------------
  const flashes = document.querySelectorAll(".flash");
  if (flashes.length) {
    setTimeout(() => {
      flashes.forEach((f) => {
        f.style.transition = "opacity 0.3s ease, transform 0.3s ease";
        f.style.opacity = "0";
        f.style.transform = "translateY(-4px)";
      });
      setTimeout(() => {
        flashes.forEach((f) => f.remove());
      }, 400);
    }, 4000); // 4s visible, then fade out
  }

  // --------------------------------------
  // Hide/show completed tasks toggle
  // --------------------------------------
  const taskList = document.querySelector(".task-list");
  if (taskList) {
    const completed = taskList.querySelectorAll(".task-card.task-done");
    if (completed.length) {
      const container = taskList.parentElement;

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.textContent = "Hide completed tasks";
      toggle.className = "btn-ghost";
      toggle.style.marginBottom = "12px";

      let hidden = false;
      toggle.addEventListener("click", () => {
        hidden = !hidden;
        completed.forEach((card) => {
          card.style.display = hidden ? "none" : "";
        });
        toggle.textContent = hidden
          ? "Show completed tasks"
          : "Hide completed tasks";
      });

      container.insertBefore(toggle, taskList);
    }
  }
});
