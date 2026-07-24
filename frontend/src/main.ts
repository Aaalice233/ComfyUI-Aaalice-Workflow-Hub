import { createApp } from "vue";
import App from "./App.vue";
import { setLocale, syncLocaleFromComfy } from "./i18n";
import "./style.css";

window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin || event.data?.type !== "AAALICE_WORKFLOW_HUB_LOCALE") return;
  setLocale(event.data.locale);
});
window.addEventListener("focus", () => void syncLocaleFromComfy());

async function bootstrap() {
  await syncLocaleFromComfy();
  createApp(App).mount("#app");
}

void bootstrap();
