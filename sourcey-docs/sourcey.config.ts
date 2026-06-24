import { defineConfig, markdown } from "sourcey";

export default defineConfig({
  name: "Quater API",
  navigation: {
    tabs: [
      {
        tab: "API Reference",
        source: markdown({
          groups: [
            {
              group: "Reference",
              pages: [
                "pages/application",
                "pages/auth",
                "pages/index",
                "pages/observability",
                "pages/parameters",
                "pages/request",
                "pages/resources",
                "pages/responses",
                "pages/testing"
              ],
            },
          ],
        }),
      },
    ],
  },
  theme: {
    preset: "default",
  },
  repo: "https://github.com/DevilsAutumn/quater",
});
