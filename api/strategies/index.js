const { setupOpenId, getOpenIdConfig, getOpenIdEmail } = require('./openidStrategy');
const openIdJwtLogin = require('./openIdJwtStrategy');
const passportLogin = require('./localStrategy');
const { setupSaml } = require('./samlStrategy');
const ldapLogin = require('./ldapStrategy');
const jwtLogin = require('./jwtStrategy');

module.exports = {
  passportLogin,
  jwtLogin,
  setupOpenId,
  getOpenIdConfig,
  getOpenIdEmail,
  ldapLogin,
  setupSaml,
  openIdJwtLogin,
};
