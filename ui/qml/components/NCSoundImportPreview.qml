import QtQuick
import QtMultimedia

Item {
    id:root
    function playSource(sourceUrl) { player.stop(); player.source=sourceUrl; player.play() }
    Component.onDestruction:player.stop()
    AudioOutput { id:output; volume:0.2 }
    MediaPlayer { id:player; audioOutput:output; loops:1 }
    Timer { interval:10000; running:player.playbackState === MediaPlayer.PlayingState; onTriggered:player.stop() }
}
