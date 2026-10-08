const { expo } = require('./app.json');
const roles = ['patient', 'doctor', 'reception'];
module.exports = () => {
  const variant = process.env.EXPO_PUBLIC_APP_WORKSPACE || '';
  if (variant && !roles.includes(variant)) throw new Error('Unknown MediFlow app workspace.');
  const suffix = variant ? `.${variant}` : '';
  return {
    ...expo,
    name: variant ? `MediFlow ${variant[0].toUpperCase()}${variant.slice(1)}` : expo.name,
    scheme: variant ? `mediflow-${variant}` : expo.scheme,
    ...(process.env.EXPO_PUBLIC_EAS_PROJECT_ID ? {extra:{eas:{projectId:process.env.EXPO_PUBLIC_EAS_PROJECT_ID}}}:{}),
    ios: {...expo.ios, bundleIdentifier: `${expo.ios.bundleIdentifier}${suffix}`},
    android: {...expo.android, package:`${expo.android.package}${suffix}`,
      ...(process.env.GOOGLE_SERVICES_JSON ? {googleServicesFile:process.env.GOOGLE_SERVICES_JSON}: {})},
  };
};
