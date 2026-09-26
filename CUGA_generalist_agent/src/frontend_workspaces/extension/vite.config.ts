import { ConfigEnv, defineConfig, normalizePath, loadEnv } from "vite";
import webExtension, { readJsonFile } from "vite-plugin-web-extension";
import { viteStaticCopy } from "vite-plugin-static-copy";
import checker from "vite-plugin-checker";
import dateFormat from "dateformat";
import path, { resolve } from "path";
import * as fs from "node:fs/promises";

async function replaceInFile(filePath) {
    try {
        let data = await fs.readFile(filePath, "utf8");
        const updatedData = data.replace(/_commonjsHelpers/g, "commonjsHelpers");
        await fs.writeFile(filePath, updatedData, "utf8");
    } catch (err) {
        if (err.code === "EACCES") {
            console.error(`Permission denied: ${filePath}`);
        } else {
            console.error(`Error processing file ${filePath}:`, err);
        }
    }
}

async function copyAndDeleteFile(oldFilePath) {
    const dir = path.dirname(oldFilePath);
    const newFilePath = path.join(dir, "commonjsHelpers.js");

    try {
        // Copy the file content
        let data = await fs.readFile(oldFilePath, "utf8");
        await fs.writeFile(newFilePath, data, "utf8");

        // Delete the old file
        await fs.unlink(oldFilePath);
    } catch (err) {
        if (err.code === "EACCES") {
            console.error(`Permission denied: ${oldFilePath}`);
        } else {
            console.error(`Error copying and deleting file ${oldFilePath}:`, err);
        }
    }
}

async function traverseDirectory(dir) {
    try {
        const files = await fs.readdir(dir, { withFileTypes: true });
        for (const file of files) {
            const fullPath = path.join(dir, file.name);
            if (file.isDirectory()) {
                await traverseDirectory(fullPath);
            } else if (file.isFile()) {
                await replaceInFile(fullPath);
                if (file.name === "_commonjsHelpers.js") {
                    await copyAndDeleteFile(fullPath);
                }
            }
        }
    } catch (err) {
        console.error(`Error reading directory ${dir}:`, err);
    }
}

function postBuildPlugin() {
    return {
        name: "vite-plugin-post-build",
        apply: "build",
        closeBundle() {
            console.log("Starting sanitizing process");
            traverseDirectory("prod");
        },
    };
}

const target = process.env.TARGET || "chrome";
function generateManifest(mode: string, env: { [x: string]: string }) {
    const isProductionMode = mode === "production";
    let manifest = readJsonFile(`src/manifest.${target}.json`);
    let manifestString = JSON.stringify(manifest);
    manifestString = replaceKeysInString(manifestString, env);
    manifest = JSON.parse(manifestString);
    const pkg = readJsonFile("package.json");
    const MAX_DESCRIPTION = 132;

    const name = isProductionMode
        ? manifest.name
        : `${manifest.name} (${mode == "development" ? "Dev" : "Prod"} - ${env["NL2UI_DEPLOYMENT_NAME"] ?? "local"})`;

    const description = isProductionMode
        ? manifest.description
        : `${target}: server "${env["NL2UI_SERVER_HOST"]}" Auth: ${env["NL2UI_AUTH_TYPE"]}`.slice(0, MAX_DESCRIPTION);

    const extensionKey = env["NL2UI_EXTENSION_KEY"] || undefined;

    return {
        ...manifest,
        key: extensionKey,
        name: name,
        //https://developer.chrome.com/docs/extensions/reference/manifest/description
        description: description,
        version: pkg.version,
    };
}

function replaceKeysInString(stringValue, env) {
    const keyIdentifier = /__(\w+)__/g;
    return stringValue.replace(keyIdentifier, (match, identifier) => {
        if (env.hasOwnProperty(identifier)) {
            let value = env[identifier];
            if (
                (typeof value === "string" || value instanceof String) &&
                value.startsWith('"') &&
                value.endsWith('"')
            ) {
                value = value.substring(1, value.length - 1);
            }
            return value;
        }
        // If the identifier is not found, leave it unchanged
        return match;
    });
}

function replaceKeysInHtml(htmlContent, keyValueMap) {
    const keyIdentifier = /__(\w+)__/g;
    return htmlContent.replace(keyIdentifier, (match, identifier) => {
        if (keyValueMap.hasOwnProperty(match)) {
            let value = keyValueMap[match];

            if (
                (typeof value === "string" || value instanceof String) &&
                value.startsWith('"') &&
                value.endsWith('"')
            ) {
                value = value.substring(1, value.length - 1);
            }
            return value;
        }
        // If the identifier is not found, leave it unchanged
        return match;
    });
}

function createViteDefine(env: { [x: string]: string }, manifest) {
    env["NL2UI_MANIFEST_VERSION"] = `v${manifest.manifest_version}`;
    env["NL2UI_TIMESTAMP"] = dateFormat(new Date(), "yyyyMMddHHMMss");

    const viteDefine = Object.entries(env).reduce((acc, [key, value]) => {
        acc[`__${key}__`] = JSON.stringify(value);
        return acc;
    }, {});

    return viteDefine;
}

// Plugin for file renaming
function renameFiles() {
    return {
        name: "rename-files",
        generateBundle(options, bundle) {
            for (const file of Object.keys(bundle)) {
                if (file.startsWith("_")) {
                    const newName = file.replace(/^_/, "");
                    bundle[newName] = bundle[file];
                    delete bundle[file];
                }
            }
        },
    };
}

export default defineConfig((config: ConfigEnv) => {
    const envFileDirectory = path.resolve(__dirname); //.env file directory
    let env = loadEnv(config.mode, envFileDirectory, "NL2UI");
    console.log("Environment: ");
    console.log(env);
    env["NL2UI_LOGOUT_URL"] = `${
        env["NL2UI_APPID_OAUTH_SERVER_URL"]
    }/cloud_directory/sso/logout?redirect_uri=${encodeURIComponent(`${env["NL2UI_DIALOG_SERVER"]}/logout`)}&client_id=${
        env["NL2UI_APPID_CLIENT_ID"]
    }`;
    const manifest = generateManifest(config.mode, env);
    const define = createViteDefine(env, manifest);
    const outputDir = config.mode == "production" ? "prod" : "build";

    if (config.mode === "production") {
        return {
            define,
            esbuild: {
                target: "es2022",
            },
            publicDir: false,
            build: {
                sourcemap: false,
                outDir: "prod",
                assetsInlineLimit: 0,
                minify: "terser",
            },
            plugins: [
                webExtension({
                    manifest: () => manifest,
                    additionalInputs: ["src/assets/sidepanel.html", "src/logWorker/log.worker.ts"],
                    browser: target,
                }),
                viteStaticCopy({
                    targets: [
                        {
                            src: normalizePath("./src/assets/*.html"),
                            dest: normalizePath("assets"),
                            transform: (content, path) => {
                                //replace __VAR_NAME__ within .html files.
                                if (path.endsWith(".html")) {
                                    return replaceKeysInHtml(content, define);
                                }

                                return content; // Return unmodified content for other files
                            },
                        },
                        {
                            src: normalizePath("./src/assets/*.(png|jpeg|yaml)"),
                            dest: normalizePath("assets"),
                        },
                        {
                            src: normalizePath("../node_modules/@ibm/plex/IBM-Plex-Sans"),
                            dest: normalizePath("fonts"),
                        },
                    ],
                }),
                // checker({
                //     typescript: true,
                // }),
            ],
            resolve: {
                alias: {
                    "@uiagent/shared": path.resolve(__dirname, "../shared/dist/index.js"),
                    "@agentic_chat": path.resolve(__dirname, "../agentic_chat/src"),
                },
            },
        };
    }

    return {
        define,
        logLevel: "error",
        esbuild: {
            target: "es2022",
        },
        publicDir: false,
        build: {
            sourcemap: true,
            watch: {
                include: [path.resolve("./src/**"), path.resolve("../sidepanel/src/**"), path.resolve("../runtime/**")],
            },
            outDir: outputDir,
            assetsInlineLimit: 0,
            minify: false,
        },
        plugins: [
            webExtension({
                manifest: () => manifest,
                additionalInputs: ["src/assets/sidepanel.html", "src/logWorker/log.worker.ts"],

                watchFilePaths: ["package.json", "manifest.chrome.json", "manifest.firefox.json"],
                browser: target,
            }),
            viteStaticCopy({
                targets: [
                    {
                        src: normalizePath("./src/assets/*.html"),
                        dest: normalizePath("assets"),
                        transform: (content, path) => {
                            //replace __VAR_NAME__ within .html files.
                            if (path.endsWith(".html")) {
                                return replaceKeysInHtml(content, define);
                            }

                            return content; // Return unmodified content for other files
                        },
                    },
                    {
                        src: normalizePath("./src/assets/*.(png|jpeg|yaml)"),
                        dest: normalizePath("assets"),
                    },
                    {
                        src: normalizePath("../node_modules/@ibm/plex/IBM-Plex-Sans"),
                        dest: normalizePath("fonts"),
                    },
                ],
            }),
            postBuildPlugin(),
        ],
        resolve: {
            alias: {
                "@uiagent/shared": path.resolve(__dirname, "../shared/dist/index.js"),
                "@agentic_chat": path.resolve(__dirname, "../agentic_chat/src"),
            },
        },
        optimizeDeps: {
            include: ["@uiagent/shared"],
        },
    };
});
