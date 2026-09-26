import { defineConfig, devices } from "@playwright/test";
import path from "path";
import dotenv from "dotenv";

configureNodeEnv();

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
    timeout: 5 * 60 * 1000, //5 minutes
    testDir: "./tests/",
    /* Run tests in files in parallel */
    fullyParallel: false,
    /* Fail the build on CI if you accidentally left test.only in the source code. */
    forbidOnly: !!process.env.CI,
    /* Retry on CI only */
    retries: process.env.CI ? 2 : 0,
    /* Opt out of parallel tests on CI. */
    workers: 2,
    /* Reporter to use. See https://playwright.dev/docs/test-reporters */
    reporter: "html",
    /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
    use: {
        /* Base URL to use in actions like `await page.goto('/')`. */
        // baseURL: 'http://127.0.0.1:3000'
        /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
        trace: "on-first-retry",
    },

    /* Configure projects for major browsers */
    projects: [
        {
            name: "chromium",
            use: { ...devices["Desktop Chrome"], channel: "chromium" },
        },
    ],

    /* Run your local dev server before starting the tests */
    // webServer: {
    //   command: '',
    //   port: 8000,
    //   cwd: baseFolder,
    //   timeout: 120 * 1000,
    //   reuseExistingServer: !process.env.CI,
    // },
});

function configureNodeEnv() {
    dotenv.config();

    if (process.env.NODE_ENV) {
        const env_path = path.resolve(process.cwd(), `.env.${process.env.NODE_ENV}`);
        dotenv.config({ path: env_path, override: true });
    }
}
