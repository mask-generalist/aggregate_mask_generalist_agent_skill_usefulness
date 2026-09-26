// VITE build consts

export const NL2UI_SERVER_HOST: string = import.meta.env.NL2UI_SERVER_HOST;
export const NL2UI_WAIT_TIMEOUT: string = import.meta.env.NL2UI_WAIT_TIMEOUT;
export const NL2UI_IAM_ENDPOINT: string = import.meta.env.NL2UI_IAM_ENDPOINT;
export const NL2UI_AUTH_TYPE: string = import.meta.env.NL2UI_AUTH_TYPE;
export const NL2UI_ENVIRONMENT: string = import.meta.env.NL2UI_ENVIRONMENT ?? "PROD";
export const NL2UI_USE_SERVER_HOST: boolean =
    String(import.meta.env.NL2UI_USE_SERVER_HOST ?? "").toLowerCase() == "true";
export enum EnvironmentTypes {
    Dev = "DEV",
    Prod = "PROD",
}
