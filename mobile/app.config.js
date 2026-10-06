const { expo } = require('./app.json');
module.exports = () => ({ ...expo,
  ...(process.env.EXPO_PUBLIC_EAS_PROJECT_ID ? {extra:{eas:{projectId:process.env.EXPO_PUBLIC_EAS_PROJECT_ID}}}:{}),
  android:{...expo.android,...(process.env.GOOGLE_SERVICES_JSON ? {googleServicesFile:process.env.GOOGLE_SERVICES_JSON}: {})},
});
