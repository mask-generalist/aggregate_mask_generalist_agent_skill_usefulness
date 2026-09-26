# NL2UI Browser Extension

This browser extension leverages the [Page Understanding] core library..

## Permissions
Read the detailed permissions required by this extension [here](docs/permissions.md).

## Contributing

This project uses [WXT](https://wxt.dev/) to support multiple browsers with one code base.

Supporting multiple browsers is not easy as there are many APIs that are not implemented across them. See [Browser support for Javascript APIs](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Browser_support_for_JavaScript_APIs).


### Build
Install the dependencies with `npm install`.

Build for development using with `npm start`. This will not minify the output javascript.

Build for production using `npm run build`.

Where you can add a flag `-b [browser]` is the browser's name:
- Use `chrome` for Chrome and Microsoft Edge.
- Use `firefox` for Firefox.
    - eg: `npm run build -b firefox`


#### Firefox
Although Firefox claims they support extension manifest v3, we couldn't make it work. So, Firefox manifest is using V2 and there are some checks in the code to verify which manifest is loaded, so the right implementation is used.

Our rules uses `:has` pseudo-selector and this is not supported by default on Firefox. You need to enable it manually. Read instructions [here](https://stackoverflow.com/a/73936256/1830639). Out-of-the-box support will come for Firefox 121: https://caniuse.com/?search=%3Ahas()

### Development
Vite has a feature that hot reloads the browser extension when source code files change. Read more on [Understanding the Development Cycle](https://vite-plugin-web-extension.aklinker1.io/guide/development.html#understanding-the-development-cycle).

However, we recommend using `npm run [browser] -- --watch --mode development` to rebuid the extension whenever a file is changed.