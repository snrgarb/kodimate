# -*- coding: utf-8 -*-
import xbmc

from kodimate import player


def test_play_sets_mime_type_and_content_lookup_when_given():
    xbmc.play_calls[:] = []
    p = player.KodimatePlayer()

    p.play('http://edge.example/1.ts', mime_type='video/mp2t')

    listitem = xbmc.play_calls[-1][1]
    assert listitem._mime_type == 'video/mp2t'
    assert listitem._content_lookup is False


def test_play_does_not_set_mime_type_when_not_given():
    xbmc.play_calls[:] = []
    p = player.KodimatePlayer()

    p.play('http://edge.example/1.ts')

    listitem = xbmc.play_calls[-1][1]
    assert not hasattr(listitem, '_mime_type')
    assert not hasattr(listitem, '_content_lookup')


def test_play_is_windowed_so_kodi_does_not_switch_to_fullscreenvideo():
    xbmc.play_calls[:] = []
    p = player.KodimatePlayer()

    p.play('http://edge.example/1.ts')

    assert xbmc.play_calls[-1][2] is True


def test_play_sets_properties_on_the_listitem_when_given():
    xbmc.play_calls[:] = []
    p = player.KodimatePlayer()

    p.play('http://edge.example/1.ts', properties={
        'inputstream': 'inputstream.ffmpegdirect',
        'inputstream.ffmpegdirect.stream_mode': 'timeshift',
    })

    listitem = xbmc.play_calls[-1][1]
    assert listitem.getProperty('inputstream') == 'inputstream.ffmpegdirect'
    assert listitem.getProperty('inputstream.ffmpegdirect.stream_mode') == 'timeshift'
