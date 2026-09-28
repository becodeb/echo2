import { Config } from "@remotion/cli/config";
// @ts-expect-error: módulo JS compartido con scripts/stills.mjs
import { webpackOverride } from "./webpack-override.mjs";

Config.overrideWebpackConfig(webpackOverride);
Config.setVideoImageFormat("png");
