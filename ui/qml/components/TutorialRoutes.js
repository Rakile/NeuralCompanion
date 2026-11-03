.pragma library

// Read presentation state only. Never invoke provider actions from this module.
function find(item, name) {
    if (!item || item.visible === false) return null
    if (String(item.objectName || "") === name) return item
    const children = item.children || []
    for (let i = 0; i < children.length; ++i) {
        const result = find(children[i], name)
        if (result) return result
    }
    return null
}

function context(item, workspace, bridge) {
    if (!item || item.visible === false) return ({})
    const route = {workspace: String(workspace)}
    if (workspace === "runtime") {
        route.runtime_section = String(item.currentSection || "runtime")
        if (route.runtime_section === "runtime") {
            route.runtime_responsibility = String(item.currentResponsibility || "language")
            const key = route.runtime_responsibility
            if (key === "language") { route.provider_kind = "language"; route.provider_id = String(bridge.viewedProviderId || "") }
            if (key === "speech") { route.provider_kind = "stt"; route.provider_id = String(bridge.viewedSpeechInputBackend || "") }
            if (key === "voice") { route.provider_kind = "tts"; route.provider_id = String(bridge.viewedSpeechOutputBackend || "") }
            if (key === "avatar") { route.provider_kind = "avatar"; route.provider_id = String(bridge.viewedAvatarProvider || "") }
        } else if (route.runtime_section === "vision") {
            route.provider_kind = "vision"
            route.provider_id = String(bridge.viewedVisionProvider || "")
        }
        const panel = find(item, "runtimeProviderSettingsPanel")
        if (panel && panel.usesSectionTabs) route.subsection = String(panel.currentSectionKey || "").replace(/^section:/, "")
        const memory = find(item, "documentMemoryWorkspace")
        if (memory) route.document_section = String(memory.selectedDocumentSection || "")
        const behavior = find(item, "coreSettingsWorkspace")
        if (behavior && route.runtime_section === "chat") route.chat_tab = String(behavior.currentChatTab || "")
        for (const name of ["orbSensorySettings", "spotifySensorySettings", "visionSourceSettings"]) {
            const sensory = find(item, name)
            if (sensory) route.sensory_tab = String(sensory.selectedTab || "")
        }
    } else if (workspace === "addons") {
        route.addon = String(bridge.selectedAddonId || "")
        route.section = String(item.currentSection || "Overview")
        const persona = find(item, "personaWorkspace")
        if (persona) {
            route.persona_tab = String(persona.selectedTab || "")
            if (route.persona_tab === "overrides") route.persona_override = String(persona.selectedOverrideTab || "")
        }
        const remote = find(item, "mainChatRemoteWorkspace")
        if (remote) route.remote_tab = String(remote.currentTab || "")
        const studio = find(item, "voiceStudioWorkspace")
        if (studio) route.section = String(studio.currentSection || route.section)
    }
    return route
}
