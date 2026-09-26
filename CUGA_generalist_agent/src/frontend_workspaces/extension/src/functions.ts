export type ManifestVersion = "v2" | "v3";
export function getManifestVersion(): ManifestVersion {
    // @ts-ignore
    //NOTE: __NL2UI_MANIFEST_VERSION__ is set by 'vite' building system according to our configuration in 'vite.config.ts' file.
    const manifest = import.meta.env.MANIFEST_VERSION;
    const manifest_version = ("v" + manifest) as ManifestVersion;
    return manifest_version;
}
