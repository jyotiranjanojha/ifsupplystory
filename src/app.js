const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const cookieParser = require('cookie-parser');
const crypto = require('crypto');
const healthRoutes = require('./routes/health');
const planningRoutes = require('./routes/planning');
const analysisRoutes = require('./routes/analysis');
const chatRoutes = require('./routes/chat');
const {
  appName,
  logLevel,
  pythonBaseUrl,
  tenantId,
  clientId,
  clientSecret,
  redirectUri,
  groupIds,
  requireGroupCheck,
  requiredAppRole,
} = require('./config/env');

const app = express();

const TENANT_ID = tenantId;
const CLIENT_ID = clientId;
const CLIENT_SECRET = clientSecret;
const REDIRECT_URI = redirectUri;
const GROUP_IDS = groupIds;
const REQUIRED_APP_ROLE = requiredAppRole;

function getGraphScopes() {
  const scopes = ['openid', 'profile', 'email', 'User.Read'];
  if (requireGroupCheck) {
    scopes.push('GroupMember.Read.All', 'Directory.Read.All');
  }
  return scopes.join(' ');
}

function decodeJwtPayload(token) {
  if (!token || typeof token !== 'string') {
    return {};
  }

  try {
    const payload = token.split('.')[1];
    if (!payload) {
      return {};
    }

    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    return JSON.parse(Buffer.from(padded, 'base64').toString('utf8'));
  } catch (err) {
    console.warn('[SSO] Unable to decode JWT payload:', err.message);
    return {};
  }
}

function userHasRequiredAppRole(accessToken, idToken) {
  if (!REQUIRED_APP_ROLE) {
    return true;
  }

  const accessClaims = decodeJwtPayload(accessToken);
  const idClaims = decodeJwtPayload(idToken);
  const claimValues = [
    ...(Array.isArray(accessClaims.roles) ? accessClaims.roles : []),
    ...(Array.isArray(idClaims.roles) ? idClaims.roles : []),
    ...(Array.isArray(accessClaims.groups) ? accessClaims.groups : []),
    ...(Array.isArray(idClaims.groups) ? idClaims.groups : []),
    ...(Array.isArray(accessClaims.wids) ? accessClaims.wids : []),
    ...(Array.isArray(idClaims.wids) ? idClaims.wids : []),
    ...(accessClaims.role ? [accessClaims.role] : []),
    ...(idClaims.role ? [idClaims.role] : []),
    ...(accessClaims.appid ? [accessClaims.appid] : []),
    ...(idClaims.appid ? [idClaims.appid] : []),
  ];

  const normalizedTarget = String(REQUIRED_APP_ROLE).trim().toLowerCase();
  const hasExactMatch = claimValues.some((value) => String(value).trim().toLowerCase() === normalizedTarget);
  if (hasExactMatch) {
    return true;
  }

  const accessRoleNames = [
    accessClaims.role,
    accessClaims.roles,
    accessClaims.app_displayname,
    accessClaims.appRole,
    accessClaims.name,
    accessClaims.upn,
  ].flat().filter(Boolean).map((value) => String(value).trim().toLowerCase());

  const idRoleNames = [
    idClaims.role,
    idClaims.roles,
    idClaims.app_displayname,
    idClaims.appRole,
    idClaims.name,
    idClaims.upn,
  ].flat().filter(Boolean).map((value) => String(value).trim().toLowerCase());

  return accessRoleNames.concat(idRoleNames).some((value) => value.includes(normalizedTarget) || normalizedTarget.includes(value));
}

function isGraphAuthorizationDenied(groupData) {
  const code = groupData?.error?.code || groupData?.code;
  const message = (groupData?.error?.message || groupData?.message || '').toLowerCase();
  return code === 'Authorization_RequestDenied' || message.includes('authorization_request_denied') || message.includes('insufficient privileges') || message.includes('not allowed to call this endpoint');
}

function canBypassGroupValidation(groupData) {
  if (requireGroupCheck) {
    return false;
  }

  return !groupData || isGraphAuthorizationDenied(groupData) || !Array.isArray(groupData?.value);
}

function ensureAzureConfig() {
  if (!TENANT_ID || !CLIENT_ID || !CLIENT_SECRET || !REDIRECT_URI || (GROUP_IDS.length === 0 && requireGroupCheck)) {
    return false;
  }

  return true;
}

app.use(cors());
app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(cookieParser());
app.use(morgan(logLevel === 'debug' ? 'dev' : 'combined'));

app.get('/login', (_req, res) => {
  if (!ensureAzureConfig()) {
    console.error('[SSO] Missing Azure auth config');
    return res.status(500).send('Authentication is not configured for this environment. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_REDIRECT_URI, and AZURE_GROUP_IDS.');
  }

  const state = crypto.randomBytes(16).toString('hex');
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: 'code',
    redirect_uri: REDIRECT_URI,
    response_mode: 'query',
    scope: getGraphScopes(),
    state,
  });

  const loginUrl = `https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/authorize?${params.toString()}`;
  console.log('[SSO] Redirecting to Azure login:', loginUrl);
  res.redirect(loginUrl);
});

app.get('/auth/callback', async (req, res) => {
  if (!ensureAzureConfig()) {
    console.error('[SSO] Missing Azure auth config on callback');
    return res.status(500).send('Authentication is not configured for this environment. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_REDIRECT_URI, and AZURE_GROUP_IDS.');
  }

  const { code, error, error_description, state } = req.query;
  console.log('[SSO] Callback received:', { error, error_description, state, hasCode: Boolean(code) });

  if (error) {
    console.error('[SSO] Azure auth error:', { error, error_description });
    return res.status(400).send(`Auth failed: ${error}`);
  }

  if (!code) {
    console.error('[SSO] Missing authorization code in callback');
    return res.status(400).send('Missing authorization code');
  }

  try {
    console.log('[SSO] Exchanging authorization code for Azure token...');
    const tokenResponse = await fetch(
      `https://login.microsoftonline.com/${TENANT_ID}/oauth2/v2.0/token`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({
          client_id: CLIENT_ID,
          client_secret: CLIENT_SECRET,
          code,
          redirect_uri: REDIRECT_URI,
          grant_type: 'authorization_code',
          scope: getGraphScopes(),
        }),
      }
    );

    const tokenData = await tokenResponse.json();
    console.log('[SSO] Token response status:', tokenResponse.status);
    console.log('[SSO] Token response payload:', JSON.stringify(tokenData, null, 2));

    if (!tokenData.access_token) {
      console.error('[SSO] Token exchange failed:', tokenData);
      return res.status(400).json({
        message: 'Token exchange failed',
        details: tokenData,
      });
    }

    if (REQUIRED_APP_ROLE) {
      const hasRequiredRole = userHasRequiredAppRole(tokenData.access_token, tokenData.id_token || '');
      console.log('[SSO] App role check:', { requiredAppRole: REQUIRED_APP_ROLE, hasRequiredRole });

      if (!hasRequiredRole) {
        console.warn('[SSO] User is not assigned to the required app role:', REQUIRED_APP_ROLE);
        return res.status(403).json({
          message: 'User is not assigned to the required app role',
          requiredAppRole: REQUIRED_APP_ROLE,
        });
      }
    }

    if (requireGroupCheck) {
      console.log('[SSO] Checking Azure group membership for groups:', GROUP_IDS);
      const groupResponse = await fetch(
        'https://graph.microsoft.com/v1.0/me/checkMemberGroups',
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${tokenData.access_token}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ groupIds: GROUP_IDS }),
        }
      );

      const groupData = await groupResponse.json();
      console.log('[SSO] Group membership response status:', groupResponse.status);
      console.log('[SSO] Group membership response payload:', JSON.stringify(groupData, null, 2));

      if (!groupResponse.ok || groupData?.error) {
        const errorMessage = groupData?.error?.message || `Graph group check failed with status ${groupResponse.status}`;
        console.error('[SSO] Azure group check failed:', errorMessage);

        if (canBypassGroupValidation(groupData)) {
          console.warn('[SSO] Azure group validation is disabled for this environment. Allowing sign-in despite Graph authorization denial.');
        } else {
          return res.status(403).json({
            message: 'Azure group validation failed',
            details: groupData?.error || groupData,
          });
        }
      }

      const isAllowed = Boolean(groupData && Array.isArray(groupData.value) && groupData.value.length > 0);

      if (!isAllowed) {
        console.warn('[SSO] User is not in the configured Azure group:', GROUP_IDS);
        return res.status(401).json({
          message: 'User is not in the configured Azure group',
          groupIds: GROUP_IDS,
        });
      }
    }

    res.cookie('access_token', tokenData.access_token, {
      httpOnly: true,
      sameSite: 'lax',
    });

    const uiUrl = new URL(`${pythonBaseUrl.replace(/\/$/, '')}/`);
    uiUrl.searchParams.set('access_token', tokenData.access_token);

    console.log('[SSO] Azure auth success. Redirecting to Python UI.');
    return res.redirect(uiUrl.toString());
  } catch (err) {
    console.error('[SSO] Auth callback error:', err);
    return res.status(500).send('Authentication failed');
  }
});

app.get('/', async (req, res) => {
  if (!ensureAzureConfig()) {
    console.error('[SSO] Missing Azure auth config on root gate');
    return res.status(500).send('Authentication is not configured for this environment. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_REDIRECT_URI, and AZURE_GROUP_IDS.');
  }

  const authHeader = req.headers.authorization;
  const tokenFromCookie = req.cookies && req.cookies.access_token;
  const token = authHeader || tokenFromCookie;

  console.log('[SSO] Root access check. Cookie present:', Boolean(tokenFromCookie), 'Auth header present:', Boolean(authHeader));

  if (!token) {
    console.log('[SSO] No token found; redirecting to Azure login');
    return res.redirect('/login');
  }

  try {
    const accessToken = token.replace(/^Bearer\s+/i, '');

    if (REQUIRED_APP_ROLE) {
      const hasRequiredRole = userHasRequiredAppRole(accessToken, '');
      console.log('[SSO] Root gate app role check:', { requiredAppRole: REQUIRED_APP_ROLE, hasRequiredRole });

      if (!hasRequiredRole) {
        console.warn('[SSO] Root gate denied access; user missing required app role:', REQUIRED_APP_ROLE);
        return res.status(403).json({
          message: 'User is not assigned to the required app role',
          requiredAppRole: REQUIRED_APP_ROLE,
        });
      }
    } else if (requireGroupCheck) {
      console.log('[SSO] Validating token against Azure group membership...');
      const groupResponse = await fetch('https://graph.microsoft.com/v1.0/me/checkMemberGroups', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ groupIds: GROUP_IDS }),
      });

      const groupData = await groupResponse.json();
      console.log('[SSO] Root gate membership response status:', groupResponse.status);
      console.log('[SSO] Root gate membership response payload:', JSON.stringify(groupData, null, 2));

      if (!groupResponse.ok || groupData?.error) {
        const errorMessage = groupData?.error?.message || `Graph group check failed with status ${groupResponse.status}`;
        console.error('[SSO] Root gate Azure group check failed:', errorMessage);

        if (canBypassGroupValidation(groupData)) {
          console.warn('[SSO] Root gate: Azure group validation disabled for this environment. Allowing access despite Graph authorization denial.');
        } else {
          return res.status(403).json({
            message: 'Azure group validation failed during root gate',
            details: groupData?.error || groupData,
          });
        }
      }

      const isAllowed = Boolean(groupData && Array.isArray(groupData.value) && groupData.value.length > 0);

      if (!isAllowed) {
        console.warn('[SSO] Root gate denied access; user not in allowed group');
        return res.status(401).json({
          message: 'User is not in the configured Azure group',
          groupIds: GROUP_IDS,
        });
      }
    }

    const uiUrl = `${pythonBaseUrl.replace(/\/$/, '')}/`;
    console.log('[SSO] Access granted; redirecting to UI:', uiUrl);
    return res.redirect(uiUrl);
  } catch (err) {
    console.error('[SSO] Auth gate error:', err);
    return res.status(401).send('Authentication failed');
  }
});

app.get('/api/auth/me', async (req, res) => {
  const token = req.cookies && req.cookies.access_token;

  if (!token) {
    return res.json({
      authenticated: false,
      displayName: null,
      login: null,
      email: null,
      source: 'none',
    });
  }

  try {
    const profileResponse = await fetch('https://graph.microsoft.com/v1.0/me', {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    const profileData = await profileResponse.json();
    if (!profileResponse.ok || profileData?.error) {
      console.warn('[SSO] /api/auth/me Graph lookup failed:', profileData?.error || profileData);
      return res.json({
        authenticated: false,
        displayName: null,
        login: null,
        email: null,
        source: 'azure-graph-error',
      });
    }

    const displayName = profileData.displayName || null;
    const login = profileData.userPrincipalName || profileData.mail || displayName;
    const email = profileData.mail || profileData.userPrincipalName || null;

    return res.json({
      authenticated: true,
      displayName,
      login,
      email,
      source: 'azure-graph',
    });
  } catch (error) {
    console.error('[SSO] /api/auth/me Graph lookup error:', error);
    return res.json({
      authenticated: false,
      displayName: null,
      login: null,
      email: null,
      source: 'azure-graph-error',
    });
  }
});

app.use(healthRoutes);
app.use(planningRoutes);
app.use(analysisRoutes);
app.use(chatRoutes);

app.use((req, res) => {
  res.status(404).json({
    error: 'Not found',
    path: req.originalUrl,
    service: 'ifspstory-node',
  });
});

module.exports = app;
