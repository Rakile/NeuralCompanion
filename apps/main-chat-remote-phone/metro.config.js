const path = require('node:path');
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
config.watchFolders = [...config.watchFolders, path.resolve(__dirname, '../../packages/nc-relay-protocol')];
config.resolver.nodeModulesPaths = [path.resolve(__dirname, 'node_modules')];
module.exports = config;
