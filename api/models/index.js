const mongoose = require('mongoose');
const { logger } = require('@librechat/data-schemas');
const { createMethods } = require('@librechat/data-schemas');
const {
  matchModelName,
  syncDefaultAgents,
  findMatchingPattern,
  isDeploymentSkillId,
} = require('@librechat/api');
const getLogStores = require('~/cache/getLogStores');

const methods = createMethods(mongoose, {
  matchModelName,
  findMatchingPattern,
  isExternalSkillId: isDeploymentSkillId,
  getCache: getLogStores,
});

const seedDatabase = async () => {
  await methods.initializeRoles();
  await methods.seedDefaultRoles();
  await methods.ensureDefaultCategories();
  await methods.seedSystemGrants();
  await syncDefaultAgents({
    findUser: methods.findUser,
    getAgent: methods.getAgent,
    createAgent: methods.createAgent,
    updateAgent: methods.updateAgent,
    grantPermission: methods.grantPermission,
    authorEmail: process.env.DEFAULT_AGENTS_AUTHOR_EMAIL || 'miguelcarrascobe@boisestate.edu',
    logger,
  });
};

module.exports = {
  ...methods,
  seedDatabase,
};
